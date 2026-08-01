from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from coco_code.evaluation.batch import (
    default_swebench_live_image,
    load_batch_manifest,
    run_batch_inference,
)
from coco_code.evaluation.docker_backend import DockerInferenceResult
from coco_code.evaluation.swebench import instance_slug


def _manifest_file(tmp_path: Path) -> Path:
    source = tmp_path / "coco-code-source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (tmp_path / "eval-config.yaml").write_text("providers: []\n", encoding="utf-8")
    (tmp_path / "eval.env").write_text("OPENAI_API_KEY=test\n", encoding="utf-8")
    problems = tmp_path / "problems"
    problems.mkdir()
    for instance_id in ("owner__repo-1", "owner__repo-2"):
        (problems / f"{instance_id}.txt").write_text("fix it\n", encoding="utf-8")

    manifest = {
        "version": 1,
        "experiment_id": "pilot-v1",
        "model_name": "deepseek-v4-pro",
        "coco_code_source": "coco-code-source",
        "config_file": "eval-config.yaml",
        "env_file": "eval.env",
        "output_dir": "results",
        "cpus": 4,
        "memory": "8g",
        "instances": [
            {
                "instance_id": "owner__repo-1",
                "problem_file": "problems/owner__repo-1.txt",
            },
            {
                "instance_id": "owner__repo-2",
                "problem_file": "problems/owner__repo-2.txt",
                "image": "custom/image:latest",
            },
        ],
    }
    path = tmp_path / "pilot.yaml"
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return path


def test_default_swebench_live_image_matches_official_python_naming() -> None:
    assert default_swebench_live_image("amoffat__sh-744") == (
        "starryzhang/sweb.eval.x86_64.amoffat_1776_sh-744:latest"
    )


def test_load_batch_manifest_resolves_paths_and_default_image(tmp_path: Path) -> None:
    manifest = load_batch_manifest(_manifest_file(tmp_path))

    assert manifest.experiment_id == "pilot-v1"
    assert manifest.output_dir == (tmp_path / "results").resolve()
    assert manifest.instances[0].image == (
        "starryzhang/sweb.eval.x86_64.owner_1776_repo-1:latest"
    )
    assert manifest.instances[1].image == "custom/image:latest"
    assert manifest.cpus == 4.0
    assert manifest.memory == "8g"


def test_run_batch_inference_writes_predictions_and_resumes(tmp_path: Path) -> None:
    manifest = load_batch_manifest(_manifest_file(tmp_path))
    calls: list[str] = []

    def fake_runner(config) -> DockerInferenceResult:
        calls.append(config.instance_id)
        status = "completed" if config.instance_id.endswith("-1") else "empty_patch"
        artifact = config.output_dir / instance_slug(config.instance_id)
        artifact.mkdir(parents=True, exist_ok=True)
        patch = "diff --git a/a b/a\n" if status == "completed" else ""
        (artifact / "run-result.json").write_text(
            json.dumps({"status": status, "duration_ms": 25}), encoding="utf-8"
        )
        (artifact / "prediction.jsonl").write_text(
            json.dumps({
                "instance_id": config.instance_id,
                "model_name_or_path": config.model_name,
                "model_patch": patch,
            }) + "\n",
            encoding="utf-8",
        )
        return DockerInferenceResult(
            instance_id=config.instance_id,
            status=status,
            exit_code=0,
            duration_ms=25,
            container_name="fake",
            artifact_dir=str(artifact),
            stdout_log=str(config.output_dir / "stdout.log"),
            stderr_log=str(config.output_dir / "stderr.log"),
        )

    first = run_batch_inference(manifest, runner=fake_runner)

    assert calls == ["owner__repo-1", "owner__repo-2"]
    assert first.status == "completed"
    assert first.ran == 2
    assert first.skipped == 0
    assert first.completed == 1
    assert first.empty_patch == 1
    assert first.not_run == 0
    assert first.errors == 0
    predictions = [
        json.loads(line)
        for line in Path(first.predictions_path).read_text(encoding="utf-8").splitlines()
    ]
    assert [item["instance_id"] for item in predictions] == [
        "owner__repo-1",
        "owner__repo-2",
    ]

    def unexpected_runner(_config):
        raise AssertionError("resume should not rerun successful instances")

    resumed = run_batch_inference(manifest, runner=unexpected_runner)
    assert resumed.ran == 0
    assert resumed.skipped == 2
    assert resumed.errors == 0


def test_filtered_rerun_preserves_other_existing_prediction(tmp_path: Path) -> None:
    manifest = load_batch_manifest(_manifest_file(tmp_path))

    def fake_runner(config) -> DockerInferenceResult:
        artifact = config.output_dir / instance_slug(config.instance_id)
        artifact.mkdir(parents=True, exist_ok=True)
        (artifact / "run-result.json").write_text(
            json.dumps({"status": "completed", "duration_ms": 25}),
            encoding="utf-8",
        )
        (artifact / "prediction.jsonl").write_text(
            json.dumps({
                "instance_id": config.instance_id,
                "model_name_or_path": config.model_name,
                "model_patch": f"patch for {config.instance_id}",
            }) + "\n",
            encoding="utf-8",
        )
        return DockerInferenceResult(
            instance_id=config.instance_id,
            status="completed",
            exit_code=0,
            duration_ms=25,
            container_name="fake",
            artifact_dir=str(artifact),
            stdout_log="stdout.log",
            stderr_log="stderr.log",
        )

    run_batch_inference(manifest, runner=fake_runner)
    filtered = run_batch_inference(
        manifest,
        resume=False,
        instance_ids={"owner__repo-1"},
        runner=fake_runner,
    )

    predictions = [
        json.loads(line)
        for line in Path(filtered.predictions_path).read_text(encoding="utf-8").splitlines()
    ]
    assert [item["instance_id"] for item in predictions] == [
        "owner__repo-1",
        "owner__repo-2",
    ]
    assert filtered.total == 2
    assert filtered.ran == 1
    assert filtered.not_run == 0


def test_run_batch_inference_rejects_unknown_instance_filter(tmp_path: Path) -> None:
    manifest = load_batch_manifest(_manifest_file(tmp_path))
    with pytest.raises(ValueError, match="not found in manifest"):
        run_batch_inference(manifest, instance_ids={"missing__repo-1"})


def test_load_batch_manifest_rejects_duplicate_instances(tmp_path: Path) -> None:
    path = _manifest_file(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["instances"].append(dict(raw["instances"][0]))
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate instance_id"):
        load_batch_manifest(path)
