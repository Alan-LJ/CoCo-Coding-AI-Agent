# CoCo Code 安装与运行

## 使用 uv（推荐）

安装 uv 后，在项目根目录执行：

```powershell
uv sync
Copy-Item .\.coco-code\config.yaml.example .\.coco-code\config.yaml
uv run coco-code
```

`uv sync` 会依据 `pyproject.toml` 和 `uv.lock` 创建或更新 `.venv`。

## 使用 venv 和 pip

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
Copy-Item .\.coco-code\config.yaml.example .\.coco-code\config.yaml
.\.venv\Scripts\coco-code.exe
```

开发环境额外安装测试依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest pytest-asyncio
```

## 配置 Provider

本地配置文件为 `.coco-code/config.yaml`。可以配置：

- `anthropic`
- `openai`
- `openai-compat`

推荐使用环境变量提供密钥：

```powershell
$env:ANTHROPIC_API_KEY = "your-key"
$env:OPENAI_API_KEY = "your-key"
```

配置文件中的 `api_key` 也可以直接填写，但该文件只能保存在本地。

## MCP

示例配置默认包含 Context7 stdio MCP。使用它需要 Node.js 和 `npx`：

```yaml
mcp_servers:
  - name: context7
    command: npx
    args: ["-y", "@upstash/context7-mcp"]
```

项目也支持带 `url` 的 Streamable HTTP/SSE MCP。

## 验证

```powershell
uv run coco-code --help
uv run pytest -q
```
