# CoCo Code 安装与运行清单

## 环境要求

- Python 3.12 或更高版本。
- 本项目虚拟环境固定使用 `.codeagent`。

## 创建或复用虚拟环境

如果 `.codeagent` 已存在，可跳过创建步骤，直接安装依赖：

```powershell
python -m venv .codeagent
.\.codeagent\Scripts\python.exe -m pip install --upgrade pip
.\.codeagent\Scripts\python.exe -m pip install -e ".[dev]"
```

## 启动 CoCo Code

```powershell
.\.codeagent\Scripts\python.exe -m coco_code
.\.codeagent\Scripts\coco-code.exe
```

## 开发验证命令

```powershell
.\.codeagent\Scripts\python.exe -m pytest
.\.codeagent\Scripts\python.exe -m ruff check src tests
.\.codeagent\Scripts\python.exe -m mypy src
```

## 配置文件

复制示例配置：

```powershell
Copy-Item .\.coco-code\config.yaml.example .\.coco-code\config.yaml
```

配置文件支持三层覆盖：

1. 用户全局：`~/.coco-code/config.yaml`
2. 项目级：`<项目根目录>/.coco-code/config.yaml`
3. 本地覆盖：`<项目根目录>/.coco-code/config.local.yaml`

后层覆盖前层。`providers` 使用整列覆盖，便于本地调试。

## API Key

可以直接写在 provider 的 `api_key` 字段，也可以省略并使用环境变量：

- `anthropic`：`ANTHROPIC_API_KEY`
- `openai` / `openai-compat`：`OPENAI_API_KEY`

PowerShell 示例：

```powershell
$env:ANTHROPIC_API_KEY = "你的 Anthropic Key"
$env:OPENAI_API_KEY = "你的 OpenAI 或兼容端点 Key"
```

上述 `$env:...` 方式只对当前 PowerShell 会话临时生效，不会写入配置文件。

不要提交 `.coco-code/config.yaml` 或 `.coco-code/config.local.yaml`，它们已在 `.gitignore` 中忽略。

## 当前已安装依赖

运行依赖：

- `textual` 8.2.7
- `rich` 15.0.0
- `anthropic` 0.112.0
- `openai` 2.44.0
- `PyYAML` 6.0.3

开发依赖：

- `pytest` 9.1.1
- `ruff` 0.15.20
- `mypy` 2.1.0