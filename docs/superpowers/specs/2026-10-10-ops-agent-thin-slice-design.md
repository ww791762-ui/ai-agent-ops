# 运维 AI Agent 端到端细线 — 设计 Spec

日期 2026-10-10　依据：`运维AI_Agent开发设计文档_v2_MVP.md`

## 1 目标

打通一条最细的端到端链路，以验证整体架构和 Prompt 的效果：

CLI 提问 → 输入脱敏 → 意图识别（必要时追问） → 从 Nacos 加载 Skill 和 Prompt → LangGraph Agent 循环 → 工具网关（脱敏 + 审计） → 运行内反思 → 带证据引用的报告。

**完成标准**

1. 在 CLI 中问"b 服务支付接口昨晚开始变慢"：
   - 系统先追问缺失的信息（时间或环境）；
   - 然后输出逐跳报告，定位到 Kong → b 服务这一跳，根因指向 DB 连接池；
   - 报告引用的证据 ID 全部真实存在；
   - 日志中的 token 显示为 `[REDACTED:<类型>]`（如 url_secret、kv_secret、bearer），手机号已掩码。
2. 问"C 服务调 OCR 走哪条链路"，能正确回答两条路径（经 ocr-proxy、直连三方）。
3. 问"C 服务 OCR 超时"，结论写成"三方响应异常（依据调用方观测）"，并对比两条路径。
4. 问"帮我重启 a 服务"，不调用任何工具，回复一期只读，并给出建议步骤。

## 2 技术选型

| 项 | 选择 |
| --- | --- |
| 语言 / 依赖管理 | Python 3.12，uv |
| Agent 编排 | LangGraph（自定义节点，不使用 prebuilt 的 `ToolNode` / `create_react_agent`） |
| 模型 | `langchain-openai` 的 `ChatOpenAI`，按 OpenAI 兼容协议调用 |
| Web | FastAPI（async） |
| 存储 | PostgreSQL 16（`pgvector/pgvector` 镜像，通过 docker compose 启动），SQLAlchemy async + psycopg 3；细线阶段用 `create_all` 建表，不引入 Alembic |
| 检查点 | `langgraph-checkpoint-postgres` 的 `AsyncPostgresSaver` |
| Prompt / Skill / 脱敏规则 | Nacos 3.2.4（本地部署），`nacos-sdk-python` v2 |
| 测试 | pytest、pytest-asyncio |

**配置**（pydantic-settings，统一使用 `OPSAGENT_` 前缀；密钥只从环境变量读取）：

| 变量 | 默认值 / 示例 |
| --- | --- |
| OPSAGENT_LLM_PROVIDER | `openai_compatible` |
| OPSAGENT_LLM_BASE_URL | `https://api.modelarts-maas.com/openai/v1` |
| OPSAGENT_LLM_MODEL | `glm-5.2` |
| OPSAGENT_LLM_API_KEY | 环境变量，必填 |
| OPSAGENT_NACOS_ADDR | `127.0.0.1:8848` |
| OPSAGENT_NACOS_NAMESPACE | `public` |
| OPSAGENT_NACOS_USERNAME / OPSAGENT_NACOS_PASSWORD | 环境变量（Nacos 已开启鉴权） |
| OPSAGENT_NACOS_LABEL | `stable` |
| OPSAGENT_DB_URL | `postgresql+psycopg://opsagent:opsagent@localhost:5432/opsagent` |
| OPSAGENT_CACHE_DIR | `.cache/nacos` |

## 3 代码结构

```
src/opsagent/
├── config.py
├── api/          # FastAPI 路由
├── runner/       # Run 生命周期：创建、后台执行图、状态写回
├── agent/        # state.py、graph.py、nodes/（每个节点一个文件）、fake_model（测试用）
├── nacos/        # PromptStore、SkillStore：加载、md5、本地缓存兜底、轮询刷新
├── gateway/      # ToolRegistry、invoke 流水线、adapters/mock、adapters/topology
├── redaction/    # Redactor：阻断 / 掩码 / 令牌化
├── topology/     # 拓扑存储、trace、实体链接
└── storage/      # ORM 模型、Repository、Alembic 迁移
cli/chat.py
nacos_seed/       # prompts/*.md、skills/<id>/{SKILL.md,skill.yaml}、redaction.yaml、publish.py
fixtures/         # topology.yaml、scenarios/*.yaml
tests/
docker-compose.yml
```

**依赖方向**：`api → runner → agent → {gateway, nacos, topology}`；`gateway → {redaction, topology, storage}`。agent 不直接访问数据库，gateway 不依赖 agent。

## 4 图结构

```mermaid
flowchart LR
    S([START]) --> R[redact_input]
    R --> I[intent]
    I -->|缺字段/多候选| C[clarify]
    C --> I
    I -->|out_of_scope| F
    I --> K[route_skill]
    K --> A[agent]
    A -->|tool_calls 且未超预算| T[tools]
    T --> A
    A -->|给出结论| X[reflect]
    A -->|超预算| F
    X -->|不通过且 reflect_rounds=0| A
    X --> F[finalize]
    F --> E([END])
```

| 节点 | 实现 |
| --- | --- |
| redact_input | 用 Redactor 处理用户最新一条消息，替换后再写入 state |
| intent | LLM 结构化输出（Prompt `ops.intent`）→ `IntentResult`。`troubleshoot` 意图必须包含环境和时间，缺失时追问。随后由程序做实体链接，把实体解析为拓扑节点 ID，并把相对时间换算为 UTC 时间范围。细线阶段支持的意图：`troubleshoot`、`topology_query`、`out_of_scope` |
| clarify | 通过 `interrupt({"question": ...})` 暂停执行，回复以 `Command(resume=answer)` 恢复。同一个 Run 最多追问 1 次；之后仍然缺失的字段采用默认值（env=prod，时间=最近 1 小时），并在报告中注明 |
| route_skill | 按意图和关键词匹配 Skill；没有匹配时使用 `generic_troubleshoot`。把 skill_id、版本、md5 写入 state 和 runs 表 |
| agent | 通过一层很薄的 `LLM` 接口（`chat` / `structured`）调用 `ChatOpenAI`，便于测试时替换为脚本化模型。只绑定 Skill 的 allowed_tools 对应的 schema；模型侧的工具名用下划线形式（`logs_search`），因为 OpenAI 协议不允许函数名中出现点号。系统消息由 `ops.system`、`SKILL.md` 和链接后的实体拼成；工具结果放在 `<untrusted_data>` 标签内 |
| tools | 对每个 tool_call 调用 `gateway.invoke(call, run_ctx)`，返回 ToolMessage（内容包含 status、data、evidence_id），并执行 `step_count += 1` |
| reflect | 先做程序检查：required_evidence 是否覆盖、证据 ID 是否存在、链路类问题是否检查了每一跳。程序检查通过后，再用 LLM 检查（`ops.reflect.inrun`）。不通过时，把问题作为消息回传给 agent，`reflect_rounds += 1` |
| finalize | 用 `ops.report` 生成 `Report` 并做 Pydantic 校验；剔除引用了不存在证据的条目，并在 `dropped_claims` 中计数；对输出做脱敏后写入 reports 表 |

**State**：`messages`、`run_id`、`session_id`、`intent`、`entities`、`skill`、`step_count`、`reflect_rounds`、`evidence_ids`、`report`、`partial_reasons`。

**路由与预算**：`step_count >= skill.max_steps`（默认 15）时直接进入 finalize，并标记 partial；`recursion_limit=60` 作为兜底。

**会话**：`thread_id = session_id`。每个用户问题对应一个新的 Run；同一会话的历史消息通过 checkpointer 带入，作为 L1 记忆。

## 5 Nacos 集成

- **Prompt**：`ops.system`、`ops.intent`、`ops.reflect.inrun`、`ops.report`，通过 `get_prompt` 按 label 获取；和 Skill 一样每 60 秒轮询一次，按 md5 判断变化。
- **Skill**：`http_5xx`、`topology_qa`、`generic_troubleshoot`。按 label 下载 ZIP，解压后得到 `SKILL.md` 和 `skill.yaml`。Python SDK 没有 Skill 订阅接口，所以每 60 秒轮询一次，按 md5 判断是否有变化。
- **脱敏规则**：Nacos 配置 `ops-agent-redaction.yaml`，group 为 `OPS_AGENT`，订阅变更。
- **本地缓存**：每次加载成功都写入 `OPSAGENT_CACHE_DIR`。Nacos 不可用时读取缓存并记录 warning；没有缓存时启动失败。
- **校验**：`skill.yaml` 中的 `allowed_tools` 必须是 ToolRegistry 的子集，`max_steps` 不能超过 30。校验失败时拒绝新版本，继续使用上一个有效版本。
- **发布**：`python nacos_seed/publish.py` 调用 Admin API，发布以上全部内容并打上 `stable` label。仓库中的 `nacos_seed/` 只是初始化种子，运行时以 Nacos 中的内容为准。
- 每个 Run 都会记录各 Prompt 和 Skill 的版本与 md5。

## 6 工具网关

**接口**：`async invoke(call: ToolCall, ctx: RunContext) -> ToolResult`

**流水线**：查注册表 → 检查是否在 Skill 白名单内 → 参数 Pydantic 校验 → 把 node_id 解析到拓扑（未登记则 `denied`）→ 执行适配器（超时 30 秒，遇到超时、429、5xx 重试 2 次）→ 脱敏（异常时 fail-closed）→ 写入 evidences 表 → 写入 tool_calls 表和审计 → 返回。

**ToolResult**：`status ∈ {ok, empty, truncated, denied, backend_error}`，另含 `data`、`evidence_id`、`redaction_stats`。

| 工具 | 实现 |
| --- | --- |
| topology.trace | 真实实现：根据 endpoint 或 node 读取 DB，返回路径和每一跳可用的工具 |
| metrics.query | mock：按 `(node_id, metric, 时间范围)` 查场景文件 |
| logs.search | mock：同上，返回日志行（含敏感数据样本） |
| changes.list | mock |
| kong.upstream_health | mock |

**mock 场景文件**（`fixtures/scenarios/*.yaml`）：以 `node_id + 工具 + 参数匹配` 为键，返回预设数据；匹配不到时返回 `empty`。场景通过环境变量 `OPSAGENT_MOCK_SCENARIO` 选择：

- `b_pay_slow`：Kong → b 服务的 upstream 延迟升高；b 服务日志出现连接池等待超时，日志中含 token 和手机号；20:05 有一次 b 服务发布；另外埋入一条提示注入日志。
- `ocr_timeout`：C → OCR 三方的调用耗时 P99 为 8 秒且有超时；C → ocr-proxy → OCR 路径正常。

## 7 脱敏

| 等级 | 规则示例 | 处理 |
| --- | --- | --- |
| block | 字段名：password、token、secret、authorization、cookie；正则：`Bearer \S+`、JWT、`AKIA…`、`-----BEGIN … PRIVATE KEY-----`、URL 参数 `token=` / `sign=`、DB 连接串密码 | 替换为 `[REDACTED:类型]` |
| mask | 手机号、身份证号（含校验位校验）、银行卡号（Luhn 校验）、邮箱 | 部分掩码 |
| tokenize | 字段名：player_id、user_id、order_id | 同一个 Run 内替换为一致的 `类型_hash前4位` |

规则从 Nacos 配置读取。脱敏在三处执行：用户输入、工具结果、最终输出。每次脱敏的命中统计写入 evidences 表的 `redaction_stats`，不记录原文。

## 8 数据表（细线阶段）

`sessions`、`runs`（含 intent、entities、skill 版本与 md5、prompt_versions、status、partial_reasons）、`tool_calls`、`evidences`、`reports`、`topo_nodes`、`topo_edges`、`topo_paths`、`audit_log`。LangGraph 检查点相关的表由 `AsyncPostgresSaver.setup()` 自行创建。

种子拓扑 `fixtures/topology.yaml` 包含 4 条典型链路，通过 `python -m opsagent.topology.load` 导入数据库。

## 9 API 与 CLI

| 接口 | 说明 |
| --- | --- |
| POST /api/v1/chat | `{session_id?, message}` → 202 `{session_id, run_id}`；如果当前会话处于 `waiting_user` 状态，这条消息作为追问的回答，以 resume 的方式继续原 Run |
| GET /api/v1/runs/{id} | 返回 `{status, question?（追问内容）, report?, step_count}` |
| GET /api/v1/evidences/{id} | 返回脱敏后的证据内容 |

细线阶段不做鉴权，只监听 127.0.0.1。

`cli/chat.py` 是一个交互式循环：发送消息 → 每秒轮询一次 Run → 遇到追问时显示问题并等待输入 → 完成后格式化输出报告（逐跳状态、假设、证据 ID、缺口）。

## 10 错误处理

| 故障 | 处理 |
| --- | --- |
| 模型接口超时、429、5xx | 重试 2 次（指数退避），失败则 Run 为 `failed` |
| 结构化输出不合格 | 回传校验错误，让模型修正 1 次；intent 仍不合格则 `failed`；报告仍不合格则输出纯文本并标记 `partial` |
| 工具返回非 ok 状态 | 照实返回给模型；finalize 时检查 `missing_evidence` 是否覆盖了这些失败 |
| 未注册的工具或越权节点 | 返回 `denied` ToolMessage 并写审计，Run 不中断 |
| 达到 max_steps | 强制 finalize，标记 `partial` |
| Nacos 不可用 | 使用缓存，没有缓存则启动失败 |
| 脱敏异常 | fail-closed，该工具结果按 `backend_error` 处理 |
| 非法的 Skill 版本 | 拒绝加载，保留上一个有效版本 |
| 追问后 30 分钟无回复 | Run 状态变为 `cancelled` |

Run 状态：`queued → running → waiting_user → completed | partial | failed | cancelled`。

## 11 测试

| 层 | 内容 |
| --- | --- |
| 单元 | Redactor 规则、网关流水线、Skill 解析与校验、拓扑 trace 与实体链接、路由与预算函数 |
| 图（假模型 + docker PG） | 用 `ScriptedChatModel`（实现 `bind_tools`，按脚本返回 AIMessage）覆盖：T3 脱敏、T5 越权工具、T7 后端不可用 → partial、T8 伪造证据 ID 被剔除、T9 多候选追问、T10 写操作请求、T14 Nacos 缓存兜底、T15 非法 Skill、T17 反思只补查 1 轮、预算耗尽 |
| 真实模型冒烟（`pytest -m llm`，手动运行） | 两个场景端到端运行，断言报告定位的跳点和根因关键词；T2 提示注入；T13 三方黑盒措辞 |

## 12 不在本次范围内

告警接入 `/events`、对话式拓扑维护、L3 经验记忆、运行后反思、真实监控和日志适配器、拆分为三个进程、IM 接入、SSE、鉴权。

## 13 风险

- **glm-5.2 的 tool calling 和结构化输出能力未经验证**：实现的第一步就是写一个最小冒烟测试来确认。如果不支持 `json_schema` 模式，结构化输出就改用 function-calling 方式，或者用 JSON 模式加 Pydantic 校验。
- **`nacos-sdk-python` 对 3.2.4 AI 接口的兼容性**：实现初期要验证 `get_prompt` 和 `download_skill_zip`。如果不兼容，改为直接调用 HTTP OpenAPI。
