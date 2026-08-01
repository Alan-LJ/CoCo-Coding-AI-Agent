from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from coco_code.evaluation.docker_backend import (
    DockerInferenceConfig,
    build_container_script,
    build_docker_inference_command,
    run_docker_inference,
)
from coco_code.evaluation.swebench import (
    HarnessConfig,
    InferenceConfig,
    InferenceResult,
    build_harness_command,
    build_coco_code_command,
    instance_slug,
    run_inference,
    write_predictions_jsonl,
)


def _init_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "eval@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Eval Test"], cwd=path, check=True
    )
    (path / "target.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=path, check=True, capture_output=True)


def test_instance_slug_is_filesystem_safe() -> None:
    assert instance_slug("owner/repo#123") == "owner_repo_123"


def test_build_coco_code_command_uses_stream_json(tmp_path: Path) -> None:
    config = InferenceConfig(
        instance_id="repo__repo-1",
        problem_statement="fix it",
        work_dir=tmp_path,
        output_dir=tmp_path,
        model_name="test-model",
        coco_code_python="python-test",
    )
    command = build_coco_code_command(config)
    assert command[:3] == ["python-test", "-m", "coco_code"]
    assert "bypassPermissions" in command
    assert command[-1] == "stream-json"


def test_run_inference_captures_patch_and_events(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    fake_agent = tmp_path / "fake_agent.py"
    fake_agent.write_text(
        """
import json
from pathlib import Path

Path("target.txt").write_text("after\\n", encoding="utf-8")
print(json.dumps({"type": "tool_use", "tool_name": "EditFile", "tool_id": "1", "args": {"path": "target.txt"}}))
print(json.dumps({"type": "compact", "message": "compacted", "before_tokens": 95000, "summary": "keep the parser constraint", "keep_message_count": 5, "keep_messages": []}))
print(json.dumps({"type": "result", "result": "done", "duration_ms": 10, "num_turns": 2, "tool_calls": [{"name": "EditFile", "is_error": False}], "usage": {"input_tokens": 100, "output_tokens": 20, "is_estimated": True}, "stop_reason": "end_turn"}))
""".strip(),
        encoding="utf-8",
    )

    result = run_inference(
        InferenceConfig(
            instance_id="repo__repo-1",
            problem_statement="fix target",
            work_dir=repo,
            output_dir=tmp_path / "artifacts",
            model_name="fake-model",
        ),
        command=[sys.executable, str(fake_agent)],
    )

    assert result.status == "completed"
    assert result.num_turns == 2
    assert result.compact_count == 1
    assert result.compactions == [{
        "before_tokens": 95000,
        "summary": "keep the parser constraint",
        "keep_message_count": 5,
    }]
    assert result.input_tokens == 100
    assert result.usage_is_estimated is True
    assert "-before" in result.model_patch
    assert "+after" in result.model_patch
    artifact_dir = Path(result.artifact_dir)
    assert (artifact_dir / "trajectory.jsonl").is_file()
    assert (artifact_dir / "trajectory-analysis.json").is_file()
    prediction = json.loads((artifact_dir / "prediction.jsonl").read_text(encoding="utf-8"))
    assert prediction["instance_id"] == "repo__repo-1"
    assert prediction["model_name_or_path"] == "fake-model"


def test_run_inference_rejects_non_git_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a git checkout"):
        run_inference(
            InferenceConfig(
                instance_id="x",
                problem_statement="x",
                work_dir=tmp_path,
                output_dir=tmp_path / "out",
                model_name="x",
            ),
            command=[sys.executable, "-c", "print('unused')"],
        )


def test_write_predictions_jsonl_uses_official_fields(tmp_path: Path) -> None:
    result = InferenceResult(
        instance_id="repo__repo-1",
        model_name_or_path="model",
        status="completed",
        model_patch="diff --git a/a b/a\n",
        duration_ms=1,
        exit_code=0,
    )
    output = tmp_path / "predictions.jsonl"
    write_predictions_jsonl([result], output)
    record = json.loads(output.read_text(encoding="utf-8"))
    assert set(record) == {"instance_id", "model_name_or_path", "model_patch"}


def test_build_harness_command(tmp_path: Path) -> None:
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text("{}\n", encoding="utf-8")
    config = HarnessConfig(
        harness_dir=tmp_path,
        harness_python="/eval/.venv/bin/python",
        predictions_path=predictions,
        run_id="coco-code-baseline",
        instance_ids=("repo__repo-1",),
    )
    command = build_harness_command(config)
    assert command[:3] == [
        "/eval/.venv/bin/python",
        "-m",
        "swebench.harness.run_evaluation",
    ]
    assert "--predictions_path" in command
    assert command[-2:] == ["--instance_ids", "repo__repo-1"]


def _docker_config(tmp_path: Path) -> DockerInferenceConfig:
    source = tmp_path / "coco_code source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    problem = tmp_path / "problem.txt"
    problem.write_text("Fix the parser without exposing this prompt.", encoding="utf-8")
    provider_config = tmp_path / "eval-config.yaml"
    provider_config.write_text(
        "providers:\n  - name: test\n    api_key: super-secret\n",
        encoding="utf-8",
    )
    return DockerInferenceConfig(
        instance_id="owner__repo-123",
        image="namespace/sweb.eval.x86_64.owner_1776_repo-123:latest",
        problem_file=problem,
        coco_code_source=source,
        config_file=provider_config,
        output_dir=tmp_path / "results",
        model_name="test/model name",
    )


def test_build_docker_inference_command_uses_read_only_secret_mounts(
    tmp_path: Path,
) -> None:
    config = _docker_config(tmp_path)
    config.output_dir.mkdir()

    command = build_docker_inference_command(
        config,
        container_name="coco-code-test",
        host_uid=1000,
        host_gid=1000,
    )
    serialized = "\n".join(command)

    assert command[:5] == ["docker", "run", "--rm", "--name", "coco-code-test"]
    assert config.image in command
    assert "target=/opt/coco-code-src,readonly" in serialized
    assert "target=/tmp/coco-code-problem.txt,readonly" in serialized
    assert "target=/tmp/coco-code-eval-config.yaml,readonly" in serialized
    assert "target=/results" in serialized
    assert "super-secret" not in serialized
    assert "Fix the parser" not in serialized

    script = command[-1]
    assert "/usr/bin/python3.11 -m venv /opt/coco-code-venv" in script
    assert "coco-code-swebench infer" in script
    assert "--instance-id owner__repo-123" in script
    assert "--model-name 'test/model name'" in script
    assert "chown -R 1000:1000 /results" in script


def test_build_container_script_falls_back_to_installing_venv(tmp_path: Path) -> None:
    script = build_container_script(
        _docker_config(tmp_path), host_uid=1000, host_gid=1000
    )
    assert "if ! /usr/bin/python3.11 -m venv" in script
    assert "apt-get install -y python3.11-venv" in script


def test_run_docker_inference_rejects_missing_config(tmp_path: Path) -> None:
    config = _docker_config(tmp_path)
    config.config_file.unlink()
    with pytest.raises(ValueError, match="config file does not exist"):
        run_docker_inference(config, command=[sys.executable, "-c", "pass"])
