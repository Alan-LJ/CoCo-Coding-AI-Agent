# CoCo Code

CoCo Code 是一个使用 Python 构建的终端 Coding Agent。它提供 Textual TUI、流式模型响应、多轮 Agent Loop、本地代码工具、通用 Web 搜索与页面读取、MCP、Skills、子 Agent/Team、会话持久化和分层权限控制。

## 主要能力

- 支持 Anthropic、OpenAI 和 OpenAI-compatible 模型接口。
- 内置 `ReadFile`、`WriteFile`、`EditFile`、`Bash`、`Glob`、`Grep`、`WebSearch`、`WebFetch`。
- 支持 stdio、Streamable HTTP 和 SSE MCP 服务。
- 支持 Plan、Accept Edits、Default 和 Bypass 权限模式。
- 支持子 Agent、Team 协作、后台任务、Skills 和 Git worktree。
- 保存项目会话、思考块、工具调用及 Agent Loop 摘要。
- 提供交互式 TUI、非交互文本输出和 NDJSON 流式输出。

## 环境要求

- Python 3.11 或更高版本
- 推荐安装 [uv](https://docs.astral.sh/uv/)
- 使用 stdio MCP 时，相关 MCP Server 可能需要 Node.js/npm

## 快速开始

使用 uv：

```powershell
git clone https://github.com/Alan-LJ/CoCo-Coding-AI-Agent.git
cd CoCo-Coding-AI-Agent
uv sync
Copy-Item .\.coco-code\config.yaml.example .\.coco-code\config.yaml
uv run coco-code
```

使用标准 venv/pip：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .\.coco-code\config.yaml.example .\.coco-code\config.yaml
.\.venv\Scripts\coco-code.exe
```

编辑 `.coco-code/config.yaml`，配置模型 provider。真实 API Key 只应保存在本地配置或环境变量中，不要提交到仓库。

## 命令行

```powershell
# 交互式 TUI
uv run coco-code

# 非交互执行
uv run coco-code -p "检查这个项目并修复测试"

# NDJSON 事件流
uv run coco-code -p "分析项目" --output-format stream-json

# 指定权限模式
uv run coco-code --mode acceptEdits

# WebSocket 远程模式
uv run coco-code --remote
```

## 项目结构

```text
coco_code/          Agent、模型客户端、工具、TUI、MCP、Skills 与 Team 实现
tests/              单元测试、集成测试和回归测试
docs/               SWE-bench 等扩展文档
.coco-code/         本地配置、会话、Skills 与运行数据（仅提交示例配置）
pyproject.toml      包、依赖和命令入口
uv.lock             可复现依赖锁文件
```

## 开发验证

```powershell
uv sync
uv run pytest -q
```

## 安全说明

- `.coco-code/config.yaml`、`.env*`、虚拟环境、日志和会话数据均被忽略。
- 写文件、编辑文件和命令执行受权限模式、规则引擎、危险命令检测及路径沙箱控制。
- `WebFetch` 会拒绝 localhost、私网和保留地址，并限制重定向和响应大小。
