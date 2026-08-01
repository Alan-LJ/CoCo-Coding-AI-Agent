"""Evaluation utilities for running CoCo Code on software-engineering benchmarks."""

from coco_code.evaluation.batch import (
    BatchInstance,
    BatchInstanceResult,
    BatchManifest,
    BatchRunResult,
    default_swebench_live_image,
    load_batch_manifest,
    run_batch_inference,
)
from coco_code.evaluation.docker_backend import (
    DockerInferenceConfig,
    DockerInferenceResult,
    build_docker_inference_command,
    run_docker_inference,
)
from coco_code.evaluation.swebench import (
    HarnessConfig,
    InferenceConfig,
    InferenceResult,
    build_harness_command,
    build_coco_code_command,
    run_harness,
    run_inference,
)
from coco_code.evaluation.trajectory import TrajectoryAnalysis, analyze_trajectory

__all__ = [
    "BatchInstance",
    "BatchInstanceResult",
    "BatchManifest",
    "BatchRunResult",
    "DockerInferenceConfig",
    "DockerInferenceResult",
    "HarnessConfig",
    "InferenceConfig",
    "InferenceResult",
    "TrajectoryAnalysis",
    "analyze_trajectory",
    "build_harness_command",
    "build_docker_inference_command",
    "build_coco_code_command",
    "default_swebench_live_image",
    "load_batch_manifest",
    "run_harness",
    "run_docker_inference",
    "run_inference",
    "run_batch_inference",
]
