"""Manifest-driven sequential SWE-bench inference batches."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from coco_code.evaluation.docker_backend import (
    DockerInferenceConfig,
    DockerInferenceResult,
    run_docker_inference,
)
from coco_code.evaluation.swebench import instance_slug


_SUCCESS_STATUSES = {"completed", "empty_patch"}


@dataclass(frozen=True)
class BatchInstance:
    instance_id: str
    problem_file: Path
    image: str


@dataclass(frozen=True)
class BatchManifest:
    experiment_id: str
    model_name: str
    coco_code_source: Path
    config_file: Path
    output_dir: Path
    instances: tuple[BatchInstance, ...]
    env_file: Path | None = None
    python_bin: str = "/usr/bin/python3.11"
    timeout_seconds: int = 3600
    bootstrap_timeout_seconds: int = 1200
    cpus: float = 8.0
    memory: str = "20g"


@dataclass
class BatchInstanceResult:
    instance_id: str
    status: str
    action: str
    duration_ms: int = 0
    artifact_dir: str = ""
    prediction_path: str = ""
    error: str = ""


@dataclass
class BatchRunResult:
    experiment_id: str
    status: str
    total: int
    ran: int
    skipped: int
    completed: int
    empty_patch: int
    not_run: int
    errors: int
    output_dir: str
    predictions_path: str
    report_path: str
    instances: list[BatchInstanceResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_swebench_live_image(
    instance_id: str,
    *,
    namespace: str = "starryzhang",
    architecture: str = "x86_64",
) -> str:
    image_instance = instance_id.replace("__", "_1776_").lower()
    return f"{namespace}/sweb.eval.{architecture}.{image_instance}:latest"


def _resolve_path(value: Any, *, base_dir: Path, field_name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"manifest field '{field_name}' must be a non-empty path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _positive_int(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"manifest field '{key}' must be a positive integer")
    return value


def _positive_float(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"manifest field '{key}' must be a positive number")
    return float(value)


def load_batch_manifest(path: Path) -> BatchManifest:
    manifest_path = path.resolve()
    if not manifest_path.is_file():
        raise ValueError(f"batch manifest does not exist: {manifest_path}")
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid batch manifest YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("batch manifest must be a YAML mapping")
    if raw.get("version", 1) != 1:
        raise ValueError("unsupported batch manifest version; expected version: 1")

    experiment_id = str(raw.get("experiment_id", "")).strip()
    model_name = str(raw.get("model_name", "")).strip()
    if not experiment_id:
        raise ValueError("manifest field 'experiment_id' must not be empty")
    if not model_name:
        raise ValueError("manifest field 'model_name' must not be empty")

    base_dir = manifest_path.parent
    instances_raw = raw.get("instances")
    if not isinstance(instances_raw, list) or not instances_raw:
        raise ValueError("manifest field 'instances' must be a non-empty list")
    instances: list[BatchInstance] = []
    seen: set[str] = set()
    for index, item in enumerate(instances_raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"manifest instance #{index} must be a mapping")
        instance_id = str(item.get("instance_id", "")).strip()
        if not instance_id:
            raise ValueError(f"manifest instance #{index} has no instance_id")
        if instance_id in seen:
            raise ValueError(f"duplicate instance_id in manifest: {instance_id}")
        seen.add(instance_id)
        image = str(item.get("image", "")).strip() or default_swebench_live_image(
            instance_id
        )
        instances.append(
            BatchInstance(
                instance_id=instance_id,
                problem_file=_resolve_path(
                    item.get("problem_file"),
                    base_dir=base_dir,
                    field_name=f"instances[{index}].problem_file",
                ),
                image=image,
            )
        )

    env_file_raw = raw.get("env_file")
    env_file = (
        _resolve_path(env_file_raw, base_dir=base_dir, field_name="env_file")
        if env_file_raw is not None
        else None
    )
    manifest = BatchManifest(
        experiment_id=experiment_id,
        model_name=model_name,
        coco_code_source=_resolve_path(
            raw.get("coco_code_source"),
            base_dir=base_dir,
            field_name="coco_code_source",
        ),
        config_file=_resolve_path(
            raw.get("config_file"),
            base_dir=base_dir,
            field_name="config_file",
        ),
        env_file=env_file,
        output_dir=_resolve_path(
            raw.get("output_dir"),
            base_dir=base_dir,
            field_name="output_dir",
        ),
        instances=tuple(instances),
        python_bin=str(raw.get("python_bin", "/usr/bin/python3.11")),
        timeout_seconds=_positive_int(raw, "timeout_seconds", 3600),
        bootstrap_timeout_seconds=_positive_int(
            raw, "bootstrap_timeout_seconds", 1200
        ),
        cpus=_positive_float(raw, "cpus", 8.0),
        memory=str(raw.get("memory", "20g")),
    )
    validate_batch_manifest(manifest)
    return manifest


def validate_batch_manifest(manifest: BatchManifest) -> None:
    if not manifest.coco_code_source.is_dir():
        raise ValueError(f"CoCo Code source directory does not exist: {manifest.coco_code_source}")
    if not (manifest.coco_code_source / "pyproject.toml").is_file():
        raise ValueError(
            f"CoCo Code source directory has no pyproject.toml: {manifest.coco_code_source}"
        )
    if not manifest.config_file.is_file():
        raise ValueError(f"CoCo Code config file does not exist: {manifest.config_file}")
    if manifest.env_file is not None and not manifest.env_file.is_file():
        raise ValueError(f"environment file does not exist: {manifest.env_file}")
    for instance in manifest.instances:
        if not instance.problem_file.is_file():
            raise ValueError(
                f"problem file does not exist for {instance.instance_id}: "
                f"{instance.problem_file}"
            )


def _read_existing_result(manifest: BatchManifest, instance_id: str) -> dict[str, Any] | None:
    result_path = manifest.output_dir / instance_slug(instance_id) / "run-result.json"
    if not result_path.is_file():
        return None
    try:
        value = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _existing_instance_record(
    manifest: BatchManifest,
    instance: BatchInstance,
) -> BatchInstanceResult:
    artifact_dir = manifest.output_dir / instance_slug(instance.instance_id)
    prediction_path = artifact_dir / "prediction.jsonl"
    existing = _read_existing_result(manifest, instance.instance_id)
    if (
        existing is not None
        and str(existing.get("status")) in _SUCCESS_STATUSES
        and prediction_path.is_file()
    ):
        return BatchInstanceResult(
            instance_id=instance.instance_id,
            status=str(existing["status"]),
            action="existing",
            duration_ms=int(existing.get("duration_ms", 0) or 0),
            artifact_dir=str(artifact_dir),
            prediction_path=str(prediction_path),
        )
    return BatchInstanceResult(
        instance_id=instance.instance_id,
        status="not_run",
        action="not_selected",
        artifact_dir=str(artifact_dir),
        prediction_path=str(prediction_path),
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _write_batch_outputs(
    manifest: BatchManifest,
    records: list[BatchInstanceResult],
) -> BatchRunResult:
    predictions: list[dict[str, Any]] = []
    for record in records:
        if record.status not in _SUCCESS_STATUSES:
            continue
        prediction_path = Path(record.prediction_path)
        try:
            lines = prediction_path.read_text(encoding="utf-8").splitlines()
            prediction = json.loads(next(line for line in lines if line.strip()))
        except (OSError, StopIteration, json.JSONDecodeError) as exc:
            record.status = "error"
            record.error = f"failed to read prediction: {exc}"
            continue
        if not isinstance(prediction, dict):
            record.status = "error"
            record.error = "prediction is not a JSON object"
            continue
        predictions.append(prediction)

    predictions_path = manifest.output_dir / "predictions.jsonl"
    predictions_text = "".join(
        json.dumps(prediction, ensure_ascii=False) + "\n"
        for prediction in predictions
    )
    _atomic_write(predictions_path, predictions_text)

    completed = sum(record.status == "completed" for record in records)
    empty_patch = sum(record.status == "empty_patch" for record in records)
    not_run = sum(record.status == "not_run" for record in records)
    errors = sum(record.status == "error" for record in records)
    ran = sum(record.action == "ran" for record in records)
    skipped = sum(record.action == "skipped" for record in records)
    result = BatchRunResult(
        experiment_id=manifest.experiment_id,
        status=(
            "completed_with_errors"
            if errors
            else "incomplete"
            if not_run
            else "completed"
        ),
        total=len(records),
        ran=ran,
        skipped=skipped,
        completed=completed,
        empty_patch=empty_patch,
        not_run=not_run,
        errors=errors,
        output_dir=str(manifest.output_dir),
        predictions_path=str(predictions_path),
        report_path=str(manifest.output_dir / "batch-results.json"),
        instances=records,
    )
    payload = result.to_dict()
    payload["updated_at"] = datetime.now(UTC).isoformat()
    _atomic_write(
        Path(result.report_path),
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )
    return result


def run_batch_inference(
    manifest: BatchManifest,
    *,
    resume: bool = True,
    fail_fast: bool = False,
    instance_ids: set[str] | None = None,
    runner: Callable[[DockerInferenceConfig], DockerInferenceResult] = run_docker_inference,
) -> BatchRunResult:
    validate_batch_manifest(manifest)
    manifest.output_dir.mkdir(parents=True, exist_ok=True)
    selected = [
        instance
        for instance in manifest.instances
        if instance_ids is None or instance.instance_id in instance_ids
    ]
    if instance_ids is not None:
        available = {instance.instance_id for instance in manifest.instances}
        unknown = sorted(instance_ids - available)
        if unknown:
            raise ValueError(f"instance_ids not found in manifest: {', '.join(unknown)}")
    if not selected:
        raise ValueError("batch selection is empty")

    records_by_id = {
        instance.instance_id: _existing_instance_record(manifest, instance)
        for instance in manifest.instances
    }

    def checkpoint() -> BatchRunResult:
        return _write_batch_outputs(
            manifest,
            [records_by_id[instance.instance_id] for instance in manifest.instances],
        )

    for instance in selected:
        artifact_dir = manifest.output_dir / instance_slug(instance.instance_id)
        prediction_path = artifact_dir / "prediction.jsonl"
        existing_record = records_by_id[instance.instance_id]
        if resume and existing_record.status in _SUCCESS_STATUSES:
            existing_record.action = "skipped"
            checkpoint()
            continue

        try:
            inference = runner(
                DockerInferenceConfig(
                    instance_id=instance.instance_id,
                    image=instance.image,
                    problem_file=instance.problem_file,
                    coco_code_source=manifest.coco_code_source,
                    config_file=manifest.config_file,
                    env_file=manifest.env_file,
                    output_dir=manifest.output_dir,
                    model_name=manifest.model_name,
                    python_bin=manifest.python_bin,
                    timeout_seconds=manifest.timeout_seconds,
                    bootstrap_timeout_seconds=manifest.bootstrap_timeout_seconds,
                    cpus=manifest.cpus,
                    memory=manifest.memory,
                )
            )
            record = BatchInstanceResult(
                instance_id=instance.instance_id,
                status=inference.status,
                action="ran",
                duration_ms=inference.duration_ms,
                artifact_dir=inference.artifact_dir,
                prediction_path=str(prediction_path),
                error="" if inference.status in _SUCCESS_STATUSES else (
                    f"docker inference exited with {inference.exit_code}"
                ),
            )
        except Exception as exc:
            record = BatchInstanceResult(
                instance_id=instance.instance_id,
                status="error",
                action="ran",
                artifact_dir=str(artifact_dir),
                prediction_path=str(prediction_path),
                error=str(exc),
            )
        records_by_id[instance.instance_id] = record
        current = checkpoint()
        if fail_fast and current.errors:
            break

    return checkpoint()
