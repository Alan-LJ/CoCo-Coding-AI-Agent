# CoCo Code SWE-bench-Live evaluation

The evaluation integration has two intentionally separate phases:

1. **Inference** runs CoCo Code in a disposable task container and writes a patch
   plus a full NDJSON trajectory.
2. **Grading** passes the prediction JSONL to the official SWE-bench-Live
   harness, which evaluates the patch in a second, clean container.

Keeping these phases separate prevents inference-time package installs and
test artifacts from leaking into the official grading environment.

## Docker inference (recommended)

The official task image already contains the repository at its base commit in
`/testbed`. `docker-infer` starts a disposable copy, creates a Python 3.11
virtual environment for CoCo Code outside the repository, and bind-mounts the
artifacts back to the WSL host.

Create a dedicated evaluation config containing only the provider(s) needed by
the selected model. Do not include host-specific MCP server commands. Prefer an
blank `api_key` field so CoCo Code falls back to the protocol's environment
variable, and place the real value in a mode-600 env file:

```bash
mkdir -p ~/.coco-code ~/swebench-results/baseline
printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY" > ~/.coco-code/swebench.env
chmod 600 ~/.coco-code/swebench.env
```

For an `openai` or `openai-compat` provider, copy its existing provider block
to `eval-config.yaml`, keep the original `base_url` and `model`, change
`api_key` to `""`, and remove the `mcp_servers` section. The fallback variable
is `OPENAI_API_KEY`. For an `anthropic` provider it is `ANTHROPIC_API_KEY`.
The evaluation config should contain exactly one provider: non-interactive
CoCo Code currently runs the first provider, while `--model-name` is the label
written to the benchmark prediction rather than a provider selector.

Run one baseline instance from the CoCo Code virtual environment:

```bash
coco-code-swebench docker-infer \
  --instance-id amoffat__sh-744 \
  --image starryzhang/sweb.eval.x86_64.amoffat_1776_sh-744:latest \
  --problem-file ~/swebench-work/amoffat__sh-744.problem.txt \
  --coco-code-source "/mnt/d/AI/coco code-python" \
  --config-file ~/.coco-code/eval-config.yaml \
  --env-file ~/.coco-code/swebench.env \
  --output-dir ~/swebench-results/baseline \
  --model-name deepseek-v4-pro \
  --cpus 8 \
  --memory 20g \
  --timeout-seconds 3600
```

The first run installs CoCo Code and its dependencies inside the temporary
container, so it is slower and requires network access. The task repository's
own Python remains unchanged (Python 3.8 in the inspected image). The provider
config is mounted outside `/testbed`, is never copied into the prediction, and
the disposable inference container is removed on exit.

If the provider key is already written directly in `eval-config.yaml`, omit
`--env-file`. Never commit either file.

## Inference in an existing checkout (low-level)

The checkout must be at the benchmark task's base commit and contain a `.git`
directory. The problem statement is stored in a UTF-8 text file.

```bash
coco-code-swebench infer \
  --instance-id amoffat__sh-744 \
  --problem-file /path/to/problem_statement.txt \
  --work-dir /testbed \
  --output-dir /results/coco-code-baseline \
  --model-name deepseek-v4-pro \
  --timeout-seconds 3600
```

Each instance produces:

```text
<output>/<instance-id>/
|-- agent.stderr.log
|-- patch.diff
|-- prediction.jsonl
|-- run-config.json
|-- run-result.json
|-- trajectory-analysis.json
`-- trajectory.jsonl
```

Every `compact` event in `trajectory.jsonl` includes the pre-compaction token
count, generated summary, and the exact recent messages retained verbatim. This
lets an offline scorer distinguish facts preserved by the summary from facts
that survived in the keep tail.

Each `usage` event and the final result also carry `is_estimated`. Standard
provider usage is preferred; if an OpenAI-compatible endpoint omits its final
streaming usage chunk, CoCo Code falls back to a request/response-size estimate
instead of silently reporting zero. Estimated and provider-reported runs must
remain distinguishable in aggregate reports.

## Trajectory efficiency analysis

Every new inference run automatically writes `trajectory-analysis.json`. Older
trajectories can be analyzed without rerunning the model:

```bash
coco-code-swebench analyze \
  --trajectory ~/swebench-results/baseline/amoffat__sh-744/trajectory.jsonl \
  --output ~/swebench-results/baseline/amoffat__sh-744/trajectory-analysis.json
```

The report separates exact repeated calls within the same workspace revision
from legitimate reads after a write. It also records successful EditFile
reversals, pytest targets, Bash commands that bypass a dedicated read/search
tool, tool errors, event counts, and whether token usage was provider-reported
or estimated. An edit reversal means an `A -> B` replacement was immediately
followed on the same file by `B -> A`; repeated reversals are a strong signal of
agent-loop oscillation.

The command runs CoCo Code with `bypassPermissions`; only use it inside an
isolated benchmark container or other disposable sandbox.

## Manifest-driven pilot batch

Use a versioned YAML manifest to keep the model, resources, task set, and
output location fixed for an experiment. Start from
`docs/swebench-batch-manifest.example.yaml`, copy it into WSL, and add the five
pilot instances selected for the experiment. Do not put an API key in the
manifest; it refers to the existing mode-600 env file instead.

```bash
cp "/mnt/d/AI/coco code-python/docs/swebench-batch-manifest.example.yaml" \
  ~/swebench-work/pilot-v1.yaml
nano ~/swebench-work/pilot-v1.yaml
```

Validate the paths and inspect the selected tasks without spending model
tokens by opening the manifest and checking each problem file. Then start the
batch:

```bash
coco-code-swebench batch-infer \
  --manifest ~/swebench-work/pilot-v1.yaml
```

Instances run **sequentially**, which is deliberate for a 32 GB development
machine. The runner checkpoints after every instance. Repeating the same
command skips instances whose `run-result.json` has status `completed` or
`empty_patch` and whose prediction still exists. Use `--rerun` only when the
same selected instances must be inferred again, because it incurs new API
costs. A filtered retry does not discard predictions produced by other
manifest instances:

```bash
coco-code-swebench batch-infer \
  --manifest ~/swebench-work/pilot-v1.yaml \
  --instance-id amoffat__sh-744 \
  --rerun
```

Batch-level outputs are updated atomically:

```text
<output>/
|-- batch-results.json       # status/action/error for every manifest instance
|-- predictions.jsonl       # all currently valid predictions, ready to grade
|-- <instance-id>/           # normal per-instance inference artifacts
|-- docker-<instance>.stdout.log
`-- docker-<instance>.stderr.log
```

`batch-results.json` distinguishes `ran`, resume-`skipped`, `not_run`, and
errors. A status of `incomplete` means at least one manifest instance has not
yet produced a valid prediction; `completed_with_errors` means at least one
attempt failed. The manifest order is preserved in `predictions.jsonl`.

## Official grading

Use the Python executable from the SWE-bench-Live virtual environment, not the
CoCo Code virtual environment:

```bash
coco-code-swebench evaluate \
  --harness-dir /home/plusl/workspace/evaluation/SWE-bench-Live \
  --harness-python /home/plusl/workspace/evaluation/SWE-bench-Live/.venv/bin/python \
  --predictions ~/swebench-results/baseline/amoffat__sh-744/prediction.jsonl \
  --instance-id amoffat__sh-744 \
  --run-id coco-code-baseline-amoffat-sh-744 \
  --max-workers 1
```

For a completed pilot batch, grade the merged file and repeat `--instance-id`
for every manifest task so the official harness evaluates exactly the fixed
cohort:

```bash
coco-code-swebench evaluate \
  --harness-dir /home/plusl/workspace/evaluation/SWE-bench-Live \
  --harness-python /home/plusl/workspace/evaluation/SWE-bench-Live/.venv/bin/python \
  --predictions ~/swebench-results/pilot-v1/predictions.jsonl \
  --instance-id amoffat__sh-744 \
  --instance-id owner__repository-issue \
  --run-id deepseek-v4-pro-pilot-v1 \
  --max-workers 1
```

Do not grade until `batch-results.json` reports `not_run: 0` and `errors: 0`.
An `empty_patch` is still a valid submitted prediction and should remain in the
denominator; it is not an infrastructure failure.

## Isolation boundary

Inference and grading never reuse a container. `docker-infer` generates the
candidate patch in one disposable container; `evaluate` passes only the
prediction JSONL to the official harness, which creates a fresh task container.
