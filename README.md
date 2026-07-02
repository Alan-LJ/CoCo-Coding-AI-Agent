# CoCo Code

CoCo Code 是一个基于 Python 的终端 AI 编程助手。项目提供 Textual TUI、流式模型响应、多轮工具调用、文件编辑、命令执行确认和多 provider 配置能力，适合用于探索类 Claude Code 的本地编程代理工作流。

## 功能特性

- 终端交互界面：基于 Textual 和 Rich 渲染对话、工具调用、执行结果和运行状态。
- 多模型 provider：支持 Anthropic、OpenAI，以及 OpenAI-compatible 接口。
- Agent Loop：支持模型在同一轮用户请求中连续读取文件、搜索、修改代码并回灌工具结果。
- 工具系统：内置 `ReadFile`、`WriteFile`、`EditFile`、`Bash`、`Glob`、`Grep`。
- 安全确认：写文件、编辑文件、执行 shell 命令前触发确认；拒绝或超时会作为结构化工具结果返回给模型。
- 模式控制：支持普通 agent 模式、`/plan` 只读计划模式和 `/do` 执行模式。
- 历史回放：保存 assistant tool calls 和 tool results，兼容 OpenAI/Anthropic 的工具调用消息格式。
- 测试覆盖：包含配置、provider、工具注册、工具执行、Agent Loop 和 TUI 相关测试。

## 技术栈

- Python 3.12+
- Textual
- Rich
- OpenAI Python SDK
- Anthropic Python SDK
- PyYAML
- pytest / ruff / mypy

## 项目结构

```text
src/coco_code/
  agent/        Agent Loop、事件类型、工具调度
  llm/          Anthropic、OpenAI、OpenAI-compatible provider
  tools/        内置工具、注册表、执行器和安全摘要
  tui/          Textual 终端界面
  config.py     配置加载和 API key 解析
  prompt.py     系统提示词构建

tests/          单元测试和 TUI 测试
.coco-code/       本地配置目录，仅提交 config.yaml.example
snake-game/     示例项目
```

## 快速开始

```powershell
python -m venv .codeagent
.\.codeagent\Scripts\python.exe -m pip install --upgrade pip
.\.codeagent\Scripts\python.exe -m pip install -e ".[dev]"
```

复制示例配置：

```powershell
Copy-Item .\.coco-code\config.yaml.example .\.coco-code\config.yaml
```

推荐使用环境变量提供 API key，不要把真实 key 写入仓库：

```powershell
$env:ANTHROPIC_API_KEY = "your-anthropic-key"
$env:OPENAI_API_KEY = "your-openai-or-compatible-key"
```

启动：

```powershell
.\.codeagent\Scripts\python.exe -m coco_code
```

或在安装后使用脚本入口：

```powershell
.\.codeagent\Scripts\coco-code.exe
```

## 配置

配置文件按以下顺序合并，后面的配置覆盖前面的配置：

1. `~/.coco-code/config.yaml`
2. `<project>/.coco-code/config.yaml`
3. `<project>/.coco-code/config.local.yaml`

`.coco-code/config.yaml` 和 `.coco-code/config.local.yaml` 应只保存在本地，不应提交到 GitHub。仓库中只保留 `.coco-code/config.yaml.example`。

示例 provider：

```yaml
providers:
  - name: OpenAI
    protocol: openai
    model: gpt-5.1

  - name: Claude
    protocol: anthropic
    model: claude-sonnet-4-5
    thinking: true

  - name: OpenAI Compatible
    protocol: openai-compat
    model: qwen3-coder
    base_url: https://example.com/v1
```

## 常用命令

运行测试：

```powershell
.\.codeagent\Scripts\python.exe -m pytest
```

代码检查：

```powershell
.\.codeagent\Scripts\python.exe -m ruff check src tests
```

类型检查：

```powershell
.\.codeagent\Scripts\python.exe -m mypy src
```

## 安全说明

提交前请确认以下内容不会进入 GitHub：

- `.codeagent/`、`.venv/` 等虚拟环境目录
- `.coco-code/config.yaml`、`.coco-code/config.local.yaml`
- `.env`、`.env.*`
- 任何包含真实 API key、token、password、secret 的文件
- 本地缓存、日志、临时测试目录和生成文件

可以提交 `.coco-code/config.yaml.example`，但其中只能包含占位配置，不能包含真实密钥。