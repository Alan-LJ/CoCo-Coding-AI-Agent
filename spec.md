# MCP 客户端 Spec

## 背景

MewCode 已经是一个能自主多轮执行任务、且具备五层权限护栏的 coding agent。但当前工具集仍主要固定在内置工具上：读写改文件、命令执行、按模式找文件、搜内容等能力需要在源码中维护。想接入 GitHub、数据库、内部服务或社区现成工具时，用户必须改代码并重新发布，工具生态被锁在编译期或安装期。

MCP（Model Context Protocol）用统一协议把“提供工具的一方（server）”和“使用工具的一方（client）”解耦。MewCode 作为 MCP Client 后，可以在启动时按配置连接多个外部 MCP Server，发现工具并包装成既有 Tool 抽象注册到工具中心。Agent 调用时不需要知道工具来自远端，同时继续复用已有权限系统和 Agent Loop 的不中断错误回灌机制。

本章只实现 MCP 的工具能力子集：配置加载、连接、初始化、列工具、工具调用、生命周期关闭，以及与现有工具中心和权限系统的衔接。MCP resources、prompts、sampling、roots 等非工具能力留给后续章节。

## 目标

- 配置驱动自动发现：启动时从配置声明的 server 列表自动连接、列出工具并注册到工具中心，无需改代码。
- 支持两种传输：本地 server 使用 stdio 子进程管道；远程 server 使用 Streamable HTTP。
- 遵循标准 MCP 会话：每个 server 完成 initialize 握手、`tools/list` 列工具、按需 `tools/call` 调用工具。
- 保持 Agent 无感：远端工具包装成既有 Tool 接口，Agent 编排层与 provider 适配层不需要区分内置工具和 MCP 工具。
- 命名空间隔离：远端工具统一命名为 `mcp__<server>__<tool>`，避免与内置工具和其他 server 的工具重名，并保留来源可追溯性。
- 多 server 生命周期管理：连接缓存、失败隔离、统一关闭；单个 server 失败不影响其他 server 或内置工具。
- 两层配置合并：从用户级与项目级配置读取 `mcp_servers`，项目级同名 server 完整覆盖用户级。
- 凭据通过环境注入：`env` 与 `headers` 的值支持 `${VAR}` 展开，避免把密钥明文写入配置。
- 复用现有权限：MCP 工具进入既有“规则 -> 模式兜底 -> 人在回路”链路；权限拒绝和远端失败都以工具结果回灌给 Agent Loop。
- 不破坏既有能力：会话、流式输出、工具执行、缓存、规划、权限五层等行为不退化。

## 功能需求

- F1: 两层 YAML 配置加载与合并
  系统从用户级配置和项目级配置读取 `mcp_servers` 段。该段是 map，key 为 server 名，value 为 server 定义。文件缺失视为空配置；文件格式非法时跳过该文件并向 stderr 输出告警，不阻断启动。两层按 server 名合并，项目级同名 server 完整覆盖用户级 server，不做字段级合并；不同名 server 保留。`mcp_servers` 不存在或为空时，MewCode 以零个 MCP Server 正常启动。

- F2: server 类型与必填字段
  每个 server 定义必须显式声明 `type`，取值为 `stdio` 或 `http`。`stdio` 类型必填 `command` 字符串，可选 `args` 字符串数组和 `env` 字符串 map。`http` 类型必填 `url` 字符串，可选 `headers` 字符串 map。`type` 非法、缺失必填字段或字段类型不匹配时，跳过该 server 并向 stderr 告警，不影响其他 server。

- F3: 环境变量展开
  `env` 与 `headers` 的值支持 `${VAR}` 形式从宿主环境变量展开。展开发生在配置加载阶段，不修改原始配置文件。未定义变量展开为空字符串并向 stderr 告警，但不阻断该 server 启动；后续是否因缺少凭据失败由 server 自行决定。`command`、`args`、server 名和远端工具名不做环境变量展开，避免命令或名称受环境间接影响。

- F4: stdio 传输
  对 `stdio` server，MewCode 使用 `command` 和 `args` 启动本地子进程，通过子进程 stdin/stdout 收发 MCP JSON-RPC 消息。配置 `env` 与宿主进程环境合并后注入子进程，同名变量以配置值覆盖宿主值。server 的 stderr 透传到宿主 stderr，便于用户排查。MewCode 退出时必须关闭 stdin、等待子进程自然退出，并在必要时终止子进程。

- F5: Streamable HTTP 传输
  对 `http` server，MewCode 使用配置的 `url` 作为 Streamable HTTP endpoint，并把 `headers` 注入请求，用于 `Authorization` 等静态鉴权头。本章只使用请求-响应式工具能力，不实现独立 SSE 订阅、不依赖 server 主动推送工具列表变化或调用进度。

- F6: MCP 会话与 JSON-RPC 处理
  每个 server 建立连接后依次完成 initialize 握手、`tools/list` 列工具，并在工具被调用时发送 `tools/call`。客户端必须遵循 JSON-RPC 2.0 请求/响应语义：请求带 id，响应按 id 唤醒对应等待方，并能处理并发请求的异步回包。协议错误、未知 id、错误响应或格式异常不得导致进程崩溃，应转换为可定位的连接错误或工具错误。

- F7: 工具发现与注册
  `tools/list` 返回的每个远端工具都会包装成 MewCode Tool 并注册到工具中心。工具描述使用远端 `description`，为空时生成包含 server 名的兜底说明。参数 schema 透传远端 `inputSchema`，不做二次裁剪。远端 `annotations.readOnlyHint == true` 映射为只读工具；缺失、非法或 false 一律按非只读处理。只有成功完成初始化和列工具的 server，其工具才会被注册。

- F8: 工具命名空间
  MCP 工具统一命名为 `mcp__<server>__<tool>`。命名空间用于避免内置工具、多 server 工具之间的冲突，并让日志、权限规则和人在回路弹窗能直接追溯来源。拼接后的工具名必须只包含 LLM 工具名允许字符 `[A-Za-z0-9_-]`，否则跳过该工具并 stderr 告警。若同一 server 返回多个拼接后同名的工具，后注册者跳过并 stderr 告警；同一 server 的其他有效工具继续注册。

- F9: 工具调用适配
  Agent 调用 MCP 工具时，适配层把参数转为 `tools/call` 请求并等待远端结果。远端返回的 `content` 中 `type=text` 的文本块按顺序拼接为 MewCode `ToolResult.content`；远端 `isError == true` 映射为 `ToolResult.is_error == true`。非 text 内容块（image、audio、resource_link、embedded_resource 等）本章不回灌给模型，丢弃并对每类或每次调用给出一次 stderr 告警。连接断开、传输错误、协议错误和超时都转换为结构化失败工具结果回灌给 Agent Loop，不把异常抛到循环外导致本轮任务直接终止。

- F10: 启动连接、超时与失败隔离
  在进入主交互界面或开始 Agent Loop 前，系统对所有配置 server 发起连接、握手和列工具。实现可以并发以缩短总耗时，但每个 server 的完整启动序列必须受 30 秒超时约束，且该超时本章不做配置项。任一 server 连接、握手、列工具失败或超时，只跳过该 server；内置工具、其他 MCP Server 和启动流程继续可用。所有 server 尝试完成后，工具中心中的工具集在本次会话内保持稳定，不做热加载。

- F11: 工具调用超时
  每次 `tools/call` 使用 30 秒超时，暂不暴露配置项。超时转换为 `is_error == true` 的工具结果，并回灌给模型，Agent Loop 可以在后续轮次调整策略。

- F12: 连接缓存与统一关闭
  每个成功启动的 server 在会话期间缓存连接与发现结果，后续工具调用复用同一连接。MewCode 正常退出或致命错误收尾时，统一关闭所有已建立连接：stdio server 关闭 stdin、等待退出并在必要时终止子进程；HTTP server 关闭会话并释放远端资源。整体关闭过程最多等待 5 秒，避免单个 server 卡住导致程序无法退出。

- F13: 权限链路无感复用
  MCP 工具作为普通工具进入现有权限执行链路。黑名单只作用于内置命令执行工具的命令串，MCP 工具不命中；路径沙箱只作用于内置文件类工具，MCP 工具不命中。规则引擎按完整工具名匹配，用户可以写精确规则如 `mcp__github__create_issue`，也可以写 glob 规则如 `mcp__github__*`。`readOnlyHint == true` 的 MCP 工具归入只读类，在默认模式下放行并可并发；其他 MCP 工具归入执行类，在默认和 acceptEdits 模式下触发人在回路，在 bypass 模式下放行。权限包不为 MCP 新增特殊后门。

## 非功能需求

- N1: 失败隔离
  单个 server 在连接、握手、列工具、调用或关闭阶段失败，不得影响内置工具、其他 server 或主 Agent Loop。

- N2: 安全默认
  只读标记缺失或非法时按非只读处理；未知 server 类型和非法字段跳过；未定义环境变量展开为空但告警；权限未明确允许时继续由现有模式兜底和人在回路决定。

- N3: provider 无关
  MCP 接入不得要求 Anthropic、OpenAI 或其他 provider 适配层了解 MCP 来源；provider 只看到统一工具定义和工具结果。

- N4: 凭据保护
  env、headers 中可能包含密钥。日志、stderr 告警、错误结果、测试快照和 UI 文案不得明文输出明显敏感值。

- N5: 启动体验可控
  无 MCP 配置时启动行为与当前版本一致。有 MCP 配置时，失败和超时应给出可定位到 server 的简明信息，且不会无限等待。

- N6: 退出干净
  程序退出后不应留下 stdio 子进程、未关闭 HTTP 会话或阻塞中的后台任务；关闭兜底超时为 5 秒。

- N7: 范围克制
  本章只实现 MCP 工具能力和必要生命周期，不实现资源配额、速率限制、审计日志、健康检查、自动重连或 MCP Server 端能力。

- N8: 代码质量
  新增模块应有聚焦测试覆盖，项目既有格式化、lint、类型检查或测试命令按当前仓库约定通过。

## 不做的事情

- 不实现 MCP resources、prompts、sampling、roots 等非工具能力。
- 不实现 `tools/list` 变更通知、调用进度通知或独立 SSE 订阅。
- 不实现健康检查、后台保活、自动重连或退避重试。
- 不实现配置热加载或运行时增删 server；配置变更需要重启生效。
- 不新增本地级 MCP 配置层；本章只合并用户级和项目级两层。
- 不做 `mcp_servers` 字段级合并；同名 server 由项目级完整覆盖用户级。
- 不对 `command`、`args`、server 名或工具名做环境变量展开。
- 不实现 OAuth 完整鉴权流程；需要鉴权的 HTTP server 通过静态 `headers` 注入 token。
- 不暴露连接、启动、调用或关闭超时配置项。
- 不把 MCP 工具纳入危险命令黑名单或路径沙箱扩展；这些层仍只作用于现有内置工具。
- 不回灌非文本内容块；image、audio、resource_link、embedded_resource 等留给后续章节。
- 不实现网络请求限制、资源配额、速率限制或审计日志。
- 不实现 MCP Server，只实现 Client。

## 验收标准

- AC1: 无 `mcp_servers` 配置时，MewCode 正常启动，内置工具集合与当前版本一致。
- AC2: 用户级和项目级配置同时存在时，按 server 名合并；同名 server 项目级完整覆盖用户级；文件缺失或非法时跳过对应文件并告警，不阻断启动。
- AC3: `stdio` 缺少 `command`、`http` 缺少 `url`、`type` 缺失或非法时，该 server 被跳过并 stderr 告警，其他 server 不受影响。
- AC4: `env` 和 `headers` 的 `${VAR}` 按宿主环境展开；未定义变量展开为空并告警；`command`、`args`、server 名和工具名不展开。
- AC5: 能启动一个 stdio MCP Server 子进程，完成 initialize 和 `tools/list`；env 注入生效；退出时子进程被清理。
- AC6: 能连接一个 Streamable HTTP MCP Server，完成 initialize 和 `tools/list`；配置 headers 被注入请求。
- AC7: 客户端能处理多个并发 JSON-RPC 请求，按响应 id 唤醒正确等待方；错误响应会转换为连接错误或工具错误。
- AC8: 远端工具注册名符合 `mcp__<server>__<tool>`；描述非空；input schema 透传；`readOnlyHint` 正确映射只读性。
- AC9: 同名远端工具来自不同 server 时互不覆盖；拼接后含非法工具名字符的工具被跳过并告警；同一 server 的其他有效工具仍可注册。
- AC10: 调用 MCP 工具成功时，远端 text content 按顺序拼接为成功工具结果，并写入会话历史。
- AC11: 远端 `isError`、协议错误、连接断开或 `tools/call` 30 秒超时时，都会转换为失败工具结果回灌给 Agent Loop，Loop 不因单次失败直接终止。
- AC12: 单个 server 启动失败或启动 30 秒超时，只跳过该 server；内置工具和其他 server 工具继续可用，并输出可定位失败原因。
- AC13: 程序退出时所有已建立 MCP 连接被关闭；stdio 子进程被终止；整体关闭最多等待 5 秒。
- AC14: 权限规则可用 `mcp__<server>__<tool>` 或 `mcp__<server>__*` 匹配 MCP 工具；只读 MCP 工具按只读类默认放行，非只读 MCP 工具按执行类触发既有权限模式；黑名单和路径沙箱不误拦 MCP 工具。
- AC15: Anthropic、OpenAI 等 provider 适配层无需 MCP 特殊逻辑；同一 MCP 工具在不同 provider 下呈现为同一 Tool schema 和 ToolResult 语义。
- AC16: 敏感 env/header 值不会明文出现在日志、stderr、UI 状态、错误结果或测试输出中。
- AC17: 新增 MCP 单元测试覆盖配置合并、变量展开、stdio/http 连接适配、工具注册、调用成功/失败、超时、关闭和权限分类；项目现有测试继续通过。
