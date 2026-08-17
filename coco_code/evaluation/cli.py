"""Command-line interface for CoCo Code SWE-bench-Live evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from coco_code.evaluation.batch import load_batch_manifest, run_batch_inference
from coco_code.evaluation.docker_backend import (
    DockerInferenceConfig,
    run_docker_inference,
)
from coco_code.evaluation.swebench import (
    HarnessConfig,
    InferenceConfig,
    run_harness,
    run_inference,
)
from coco_code.evaluation.trajectory import analyze_trajectory


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coco-code-swebench",
        description="Run CoCo Code inference and official SWE-bench-Live grading.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    infer = subparsers.add_parser(
        "infer", help="Run CoCo Code in an existing task checkout and export a patch."
    )
    infer.add_argument("--instance-id", required=True)
    infer.add_argument("--problem-file", required=True, type=Path)
    infer.add_argument("--work-dir", required=True, type=Path)
    infer.add_argument("--output-dir", required=True, type=Path)
    infer.add_argument("--model-name", required=True)
    infer.add_argument("--coco-code-python", default=sys.executable)
    infer.add_argument("--timeout-seconds", type=_positive_int, default=3600)

    docker_infer = subparsers.add_parser(
        "docker-infer",
        help="Create a disposable task container, run CoCo Code, and export a patch.",
    )
    docker_infer.add_argument("--instance-id", required=True)
    docker_infer.add_argument("--image", required=True)
    docker_infer.add_argument("--problem-file", required=True, type=Path)
    docker_infer.add_argument("--coco-code-source", required=True, type=Path)
    docker_infer.add_argument("--config-file", required=True, type=Path)
    docker_infer.add_argument("--env-file", type=Path, default=None)
    docker_infer.add_argument("--output-dir", required=True, type=Path)
    docker_infer.add_argument("--model-name", required=True)
    docker_infer.add_argument("--python-bin", default="/usr/bin/python3.11")
    docker_infer.add_argument("--timeout-seconds", type=_positive_int, default=3600)
    docker_infer.add_argument(
        "--bootstrap-timeout-seconds", type=_positive_int, default=1200
    )
    docker_infer.add_argument("--cpus", type=_positive_float, default=8.0)
    docker_infer.add_argument("--memory", default="20g")

    analyze = subparsers.add_parser(
        "analyze", help="Analyze a stream-json trajectory for loop inefficiencies."
    )
    analyze.add_argument("--trajectory", required=True, type=Path)
    analyze.add_argument("--output", type=Path, default=None)

    batch_infer = subparsers.add_parser(
        "batch-infer",
        help="Run a manifest-defined inference batch sequentially with resume support.",
    )
    batch_infer.add_argument("--manifest", required=True, type=Path)
    batch_infer.add_argument(
        "--rerun", action="store_true", help="Rerun successful existing instances."
    )
    batch_infer.add_argument("--fail-fast", action="store_true")
    batch_infer.add_argument("--instance-id", action="append", default=[])

    evaluate = subparsers.add_parser(
        "evaluate", help="Grade an existing predictions JSONL with the official harness."
    )
    evaluate.add_argument("--harness-dir", required=True, type=Path)
    evaluate.add_argument("--harness-python", required=True)
    evaluate.add_argument("--predictions", required=True, type=Path)
    evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--dataset-name", default="SWE-bench-Live/SWE-bench-Live")
    evaluate.add_argument("--split", default="lite")
    evaluate.add_argument("--namespace", default="starryzhang")
    evaluate.add_argument("--max-workers", type=_positive_int, default=1)
    evaluate.add_argument("--timeout-seconds", type=_positive_int, default=7200)
    evaluate.add_argument("--instance-id", action="append", default=[])
    evaluate.add_argument("--log-path", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "infer":
        if not args.problem_file.is_file():
            raise SystemExit(f"problem file does not exist: {args.problem_file}")
        config = InferenceConfig(
            instance_id=args.instance_id,
            problem_statement=args.problem_file.read_text(encoding="utf-8"),
            work_dir=args.work_dir,
            output_dir=args.output_dir,
            model_name=args.model_name,
            timeout_seconds=args.timeout_seconds,
            coco_code_python=args.coco_code_python,
        )
        result = run_inference(config)
        print(json.dumps({
            "instance_id": result.instance_id,
            "status": result.status,
            "duration_ms": result.duration_ms,
            "num_turns": result.num_turns,
            "compact_count": result.compact_count,
            "usage_is_estimated": result.usage_is_estimated,
            "patch_bytes": len(result.model_patch.encode("utf-8")),
            "artifact_dir": result.artifact_dir,
            "errors": result.errors,
        }, ensure_ascii=False))
        raise SystemExit(0 if result.status in {"completed", "empty_patch"} else 1)

    if args.command == "docker-infer":
        result = run_docker_inference(
            DockerInferenceConfig(
                instance_id=args.instance_id,
                image=args.image,
                problem_file=args.problem_file,
                coco_code_source=args.coco_code_source,
                config_file=args.config_file,
                env_file=args.env_file,
                output_dir=args.output_dir,
                model_name=args.model_name,
                python_bin=args.python_bin,
                timeout_seconds=args.timeout_seconds,
                bootstrap_timeout_seconds=args.bootstrap_timeout_seconds,
                cpus=args.cpus,
                memory=args.memory,
            )
        )
        print(
            json.dumps(
                {
                    "instance_id": result.instance_id,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "exit_code": result.exit_code,
                    "artifact_dir": result.artifact_dir,
                    "stdout_log": result.stdout_log,
                    "stderr_log": result.stderr_log,
                },
                ensure_ascii=False,
            )
        )
        raise SystemExit(0 if result.status in {"completed", "empty_patch"} else 1)

    if args.command == "analyze":
        analysis = analyze_trajectory(args.trajectory)
        rendered = json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return

    if args.command == "batch-infer":
        result = run_batch_inference(
            load_batch_manifest(args.manifest),
            resume=not args.rerun,
            fail_fast=args.fail_fast,
            instance_ids=set(args.instance_id) if args.instance_id else None,
        )
        print(json.dumps({
            "experiment_id": result.experiment_id,
            "status": result.status,
            "total": result.total,
            "ran": result.ran,
            "skipped": result.skipped,
            "completed": result.completed,
            "empty_patch": result.empty_patch,
            "not_run": result.not_run,
            "errors": result.errors,
            "predictions_path": result.predictions_path,
            "report_path": result.report_path,
        }, ensure_ascii=False))
        raise SystemExit(0 if result.errors == 0 else 1)

    config = HarnessConfig(
        harness_dir=args.harness_dir,
        harness_python=args.harness_python,
        predictions_path=args.predictions,
        run_id=args.run_id,
        dataset_name=args.dataset_name,
        split=args.split,
        namespace=args.namespace,
        max_workers=args.max_workers,
        timeout_seconds=args.timeout_seconds,
        instance_ids=tuple(args.instance_id),
    )
    raise SystemExit(run_harness(config, log_path=args.log_path))


if __name__ == "__main__":
    main()
