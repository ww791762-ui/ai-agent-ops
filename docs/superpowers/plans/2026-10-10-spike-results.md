# Spike 结论（2026-10-10）

脚本：`scripts/spikes/llm_check.py`、`scripts/spikes/nacos_check.py`（一次性脚本，不进入正式代码）。
环境：nacos-sdk-python 3.2.0，Nacos 服务端 3.2.4（`127.0.0.1:8848`，namespace `public`），模型 glm-5.2（ModelArts MaaS OpenAI 兼容接口）。
Nacos 接口的行为除实测外，还对照了 Nacos 3.2.4 源码（`ai/.../controller/PromptAdminController.java`、`SkillAdminController.java`、`service/skills/SkillOperationServiceImpl.java`、`service/prompt/PromptOperationServiceImpl.java`）。

## 模型 glm-5.2

- tool calling：**可用**。

  ```
  [tool calling] tool_calls = [{'name': 'metrics_query', 'args': {'node_id': 'svc-b', 'metric': 'error_rate'}, 'id': 'call_3dbe…', 'type': 'tool_call'}]
  ```

- 结构化输出 function_calling：**可用**。

  ```
  [structured:function_calling] = city='北京' unit='摄氏度'
  ```

- json_schema：**不可用**。模型把 JSON 包在 Markdown 代码块里返回，解析失败：

  ```
  [structured:json_schema] FAILED: 1 validation error for Weather
    Invalid JSON: expected value at line 1 column 1 [type=json_invalid, input_value='```json\n{\n  "city": "...t": "摄氏度"\n}\n```', input_type=str]
  ```

- json_mode：**可用**。

  ```
  [structured:json_mode] = city='北京' unit='摄氏度'
  ```

- 采用的方式：`function_calling`（`Settings.llm_structured_method` 的默认值不变；`.env.example` 已补上 `OPSAGENT_LLM_STRUCTURED_METHOD=function_calling`）。json_mode 可作为备选。

## Nacos 3.2.4

### 登录接口与 token 传递方式

- `POST /nacos/v3/auth/user/login`，表单参数 `username`、`password`。
- 返回 JSON 的键为 `accessToken`、`globalAdmin`、`tokenTtl`、`username`。
- 后续 Admin 接口用 query 参数 `accessToken=<token>` 传递 token，已验证可用。
- 所有 Admin 接口的返回结构都是 `{"code": 0, "message": "success", "data": …}`。错误时 HTTP 状态码为 4xx，并带非 0 的 `code`，例如 `20004 resource not found`、`20002 parameter validate error`。

### 发布 Prompt / 绑定 label

**计划原文的接口能调通，但 SDK 读不到：**

```
POST /v3/admin/ai/prompt -> 200 {"code":0,"message":"success","data":true}
PUT /v3/admin/ai/prompt/label -> 200 {"code":0,"message":"success","data":true}
prompt FAILED: NacosException('Error [404]: Prompt version not online: spike.test@1.0.0')
```

原因：`POST /v3/admin/ai/prompt` 是 3.2.0 的旧接口（源码中标为 `@Deprecated`），实际执行的是 `createDraft + submit`。版本停在 `reviewing` 状态，审核流水线已经 `APPROVED`，但版本没有上线。

**改用以下流程后成功（实测，全部是表单参数，namespaceId 显式传）：**

| 步骤 | 接口 | 参数 |
|---|---|---|
| 1. 创建草稿 | `POST /v3/admin/ai/prompt/draft` | `namespaceId`、`promptKey`、`targetVersion`、`template`、`commitMsg`（可选），返回 `data` 为版本号 |
| 2. 上线 | `POST /v3/admin/ai/prompt/force-publish` | `namespaceId`、`promptKey`、`version`、`updateLatestLabel=true`。跳过审核流水线，可以从 draft、reviewing 或 reviewed 状态直接变为 online |
| 3. 设置 label | `PUT /v3/admin/ai/prompt/labels` | `namespaceId`、`promptKey`、`labels`，其中 `labels` 是 **JSON 字符串**，例如 `{"stable":"1.0.0"}`。会整体替换 label 表，但服务端会保留已有的 `latest` |
| 查询详情 | `GET /v3/admin/ai/prompt/governance` | `namespaceId`、`promptKey`。返回 `labels`、`versionDetails[{version,status}]`；资源不存在时返回 404 |

```
POST /v3/admin/ai/prompt/draft -> 200 {"code":0,"message":"success","data":"1.0.0"}
POST /v3/admin/ai/prompt/force-publish -> 200 {"code":0,"message":"success","data":"ok"}
PUT /v3/admin/ai/prompt/labels -> 200 {"code":0,"message":"success","data":"ok"}
GET /v3/admin/ai/prompt/governance -> 200 {… "latestVersion":"1.0.0", "onlineCnt":1, "labels":{"stable":"1.0.0","latest":"1.0.0"} …}
```

另有两个接口：`POST /v3/admin/ai/prompt/publish` 只能发布已审核通过的 reviewing 版本，而审核是异步流水线（约 3 秒）；旧接口 `PUT /prompt/label`（单个 label，服务端合并）也能用，但已废弃。正式代码都不使用这两个接口。

### 上传 Skill / 发布版本 / 设置 label

**计划原文的接口有两个问题：**

```
POST /v3/admin/ai/skills/upload/batch -> 200 {"code":0,"message":"success","data":{"succeeded":["spike-skill"],"failed":[]}}
POST /v3/admin/ai/skills/force-publish -> 404 {"code":20004,"message":"resource not found","data":"skill version not found: spike-skill@1.0.0"}
```

1. `upload/batch` 不读 `skill.yaml`，也不接受 `targetVersion` 参数。版本号的来源依次是：SKILL.md frontmatter 中的 `version`（或 `metadata.version`）、zip 里的 `_meta.json`、`targetVersion` 参数，都没有时默认为 `0.0.1`。所以上传后实际版本是 `0.0.1`，处于 draft 状态。
2. **Skill 名称只允许小写字母、数字和连字符**，下划线会被拒绝。仓库中的 `http_5xx`、`topology_qa`、`generic_troubleshoot` 都不合法：

   ```
   POST /v3/admin/ai/skills/upload -> 400 {"code":20002,"message":"parameter validate error","data":"Skill name may only contain lowercase letters, numbers, and hyphens, and must not start or end with a hyphen"}
   ```

**改用以下流程后成功（实测）：**

| 步骤 | 接口 | 参数 |
|---|---|---|
| 1. 上传（单个） | `POST /v3/admin/ai/skills/upload`（multipart） | `namespaceId`、`overwrite=true`、`targetVersion`、`commitMsg`（可选）、`file`（zip，`<name>/SKILL.md` 等）。返回 `data` 为 skill 名称；skill 名称取自 SKILL.md frontmatter 的 `name` |
| 2. 上线 | `POST /v3/admin/ai/skills/force-publish` | `namespaceId`（必填）、`skillName`、`version`、`updateLatestLabel=true` |
| 3. 设置 label | `PUT /v3/admin/ai/skills/labels` | `namespaceId`、`skillName`、`labels`，其中 `labels` 是 **JSON 字符串对象**，例如 `{"latest":"1.0.0","stable":"1.0.0"}`。**会整体替换 label 表，包括 `latest`**，所以要先读出现有 label 再合并 |
| 查询详情 | `GET /v3/admin/ai/skills` | `namespaceId`、`skillName`。返回 `labels`、`versions[{version,status}]`；不存在时返回 404 |

```
POST /v3/admin/ai/skills/upload -> 200 {"code":0,"message":"success","data":"spike-skill"}
POST /v3/admin/ai/skills/force-publish -> 200 {"code":0,"message":"success","data":"ok"}
PUT /v3/admin/ai/skills/labels -> 200 {"code":0,"message":"success","data":"ok"}
GET /v3/admin/ai/skills -> 200 {… "name":"spike-skill", "labels":{"latest":"1.0.0","stable":"1.0.0"}, "editingVersion":null, …}
```

注意事项：

- 使用 `overwrite=true` 上传时，如果目标版本号已经存在且没有编辑中的草稿，服务端会**自动升一个 patch 版本**（源码 `resolveFinalUploadVersion`），不会报错。所以发布脚本应先查询版本是否已存在，已存在就不再上传。
- label 指向的版本不存在时，`PUT labels` 仍然返回 200（第一次运行时把 stable 指向了不存在的 1.0.0，接口照样返回 `"data":"ok"`），服务端不做校验。
- 首次上传成功后，`/v3/admin/ai/skills/labels` 在 admin 路径下就存在，不需要改用控制台接口 `/v3/console/ai/skills/labels`。

### label 语义（额外验证）

先发布 1.0.0 并设置 stable=1.0.0，再发布 1.0.1（`updateLatestLabel=true`）。之后：

```
skill labels after force-publish 1.0.1: {'latest': '1.0.1', 'stable': '1.0.0'}
prompt labels after force-publish 1.0.1: {'stable': '1.0.0', 'latest': '1.0.1'}
label=stable: prompt version=1.0.0 template='hello {{name}}'; skill SKILL.md=b'---\nversion: 1.0.0\nname: spike-skill\ndes'
label=latest: prompt version=1.0.1 template='hello v2 {{name}}'; skill SKILL.md=b'---\nversion: 1.0.1\nname: spike-skill\ndes'
```

结论：force-publish 只移动 `latest`，不影响其他 label；SDK 按 label 读取的结果正确。

**风险**：SDK 的 `get_prompt` 遇到**不存在的 label 时会静默回退到 latest**，不报错（`label="nope"` 返回了 1.0.1）。Skill 遇到不存在的 label 会报 404。

### 发布配置

- `POST /v3/admin/cs/config`：**路径正确**，表单参数为 `namespaceId`、`dataId`、`groupName`、`content`、`type=yaml`。

  ```
  POST /v3/admin/cs/config -> 200 {"code":0,"message":"success","data":true}
  ```

### SDK 读取

导入路径：`from v2.nacos.ai.nacos_ai_service import NacosAIService`。计划原文的 `from v2.nacos import NacosAIService` 不成立。另外两个导入：`from v2.nacos.ai.model.ai_param import GetPromptParam, DownloadSkillParam`，`from v2.nacos import ClientConfigBuilder, ConfigParam, NacosConfigService`。

- **`get_prompt`**：返回 `v2.nacos.ai.model.prompt.prompt.Prompt`（pydantic 模型），走 gRPC 的 `QueryPromptRequest`。
  - 模板字段名为 `template`，版本字段名为 `version`。其余字段有 `promptKey`、`md5`、`variables`。
  - 输出片段：

    ```
    prompt type: <class 'v2.nacos.ai.model.prompt.prompt.Prompt'> fields: {'promptKey': 'spike.test', 'version': '1.0.0', 'template': 'hello {{name}}', 'md5': 'b49c81ce…', 'variables': None}
    ```

  - Prompt 不存在时抛 `NacosException('Error [404]: Prompt not found: …')`；版本没有上线时抛 `Prompt version not online`；label 不存在时回退到 latest（见上一节）。
- **`download_skill_zip`**：返回 `bytes`，走 HTTP 的 `GET /v3/client/ai/skills`。
  - ZIP 目录结构为 `<skill名称>/<相对路径>`，与上传时一致，`skill.yaml` 等附加文件原样保留。
  - 服务端会改写 SKILL.md 的 frontmatter，在开头插入 `version: <版本>`，所以下载得到的 SKILL.md 与仓库中的源文件字节不同。

    ```
    names: ['spike-skill/SKILL.md', 'spike-skill/skill.yaml']
    spike-skill/SKILL.md => b'---\nversion: 1.0.0\nname: spike-skill\ndescription: spike\n---\n# spike\n'
    spike-skill/skill.yaml => b'id: spike-skill\nversion: 1.0.0\n'
    ```

  - Skill 不存在或 label 不存在时抛 `NacosException('Error [404]: skill not found')`。名称不合法（含下划线）时抛 `Error [500] … HTTP error: 400`。
- **`get_config`**：**可用**，`get_config(ConfigParam(data_id="spike.yaml", group="OPS_AGENT"))` 返回 `'a: 1'`。配置不存在时**返回空字符串 `''`**，不抛异常。

## 测试数据清理

用 Admin API 删除（两轮运行之后各删除一次），删除后用 GET 确认已不存在：

```
DELETE /v3/admin/ai/prompt?namespaceId=public&promptKey=spike.test            -> 200 {"code":0,"message":"success","data":true}
DELETE /v3/admin/ai/skills?namespaceId=public&skillName=spike-skill           -> 200 {"code":0,"message":"success","data":"ok"}
DELETE /v3/admin/cs/config?namespaceId=public&dataId=spike.yaml&groupName=OPS_AGENT -> 200 {"code":0,"message":"success","data":true}
GET /v3/admin/ai/skills?skillName=spike-skill        -> 404 Skill not found: spike-skill
GET /v3/admin/ai/prompt/governance?promptKey=spike.test -> 404 Prompt not found: spike.test
GET /v3/admin/cs/config?dataId=spike.yaml…           -> 404 Config not exist
```

`spike_skill`（下划线名称）上传时就被拒绝了，Nacos 中没有残留。删除 Prompt 会删掉所有版本、存储内容和旧版 mirror 配置，删除 Skill 会删掉整个 Skill，这两个接口都不需要先下线版本。另外确认了 Nacos 中目前没有 `http-5xx`、`topology-qa`、`generic-troubleshoot`，后续发布不会和已有资源重名。

## 对后续任务的影响

- **Task 6 SdkNacosSource**（`src/opsagent/nacos/source.py`）：
  - 导入 `NacosAIService` 时用 `v2.nacos.ai.nacos_ai_service`（已经是这个路径），字段 `p.template`、`p.version` 正确。
  - `get_skill_zip` 改为用 `nacos_skill_name(name)` 下载，即把下划线换成连字符。内部 Skill id 仍然是 `http_5xx`，`ConfigStore` 和 `skill.yaml` 都不用改。
  - `get_prompt` 拿到 `None` 或 `template is None` 时抛 `LookupError`。
  - `get_config` 拿到空字符串时抛 `LookupError`，让 `ConfigStore` 走缓存或回退逻辑。
  - 已知限制：Prompt 的 label 不存在时会静默回退到 latest，客户端无法察觉，只能靠发布脚本保证 label 已绑定。
- **Task 8 `nacos_seed/publish.py` 的常量**：
  - Prompt：`PROMPT_DETAIL=GET /v3/admin/ai/prompt/governance`、`PROMPT_DRAFT=POST /v3/admin/ai/prompt/draft`、`PROMPT_PUBLISH=POST /v3/admin/ai/prompt/force-publish`、`PROMPT_LABELS=PUT /v3/admin/ai/prompt/labels`。
  - Skill：`SKILL_DETAIL=GET /v3/admin/ai/skills`、`SKILL_UPLOAD=POST /v3/admin/ai/skills/upload`（单个上传，带 targetVersion）、`SKILL_PUBLISH=POST /v3/admin/ai/skills/force-publish`、`SKILL_LABELS=PUT /v3/admin/ai/skills/labels`。
  - 配置：`CONFIG_PUBLISH=POST /v3/admin/cs/config` 不变。
  - `labels` 参数是 JSON 字符串，内容为“现有 label 合并本次 label”。
  - 上传前把 zip 目录名和 SKILL.md 的 `name` 换成 Nacos 合法名称（`skill_upload_zip`）。
  - 某个版本如果已经存在，就不再上传或创建草稿；只有版本还没上线时才调用 force-publish。这样重复运行是幂等的。
  - `batch_zip` 和 `upload/batch` 不再使用。
- **Task 9 OpenAICompatLLM 的 method 参数**：用 `function_calling`（默认值不变）。不要用 `json_schema`。如果以后需要备选，可以用 `json_mode`。

## Prompt 调优记录（Task 15 冒烟）

### 第 1 轮：3 failed / 1 passed（13 分钟）
- `test_b_pay_slow_finds_conn_pool`、`test_ocr_timeout_black_box_wording`：`reflect` 节点结构化调用 `OpenAITimeoutError`（60 秒 × 3 次）。
  逐次计时（b_pay_slow，默认开启思考）：IntentResult 700 字 24s；chat 7–43s；ReflectVerdict 8.4k 字 78s；Report 8.7k 字 151s。
  对照实验：同一短问题默认 21.8s（573 输出 token 中 reasoning 534），`extra_body={"thinking":{"type":"disabled"}}` 7.6s（reasoning 0）。
  关闭思考后整轮 b_pay_slow：ReflectVerdict 4.5s、Report 73.5s，报告同样定位到 v2.3.1 把 maxPoolSize 50→20，质量相当。
  **代码修正**：新增 `llm_extra_body`（默认关闭思考，设为 `{}` 恢复）；`llm_timeout_s` 60 → 180。
- `test_restart_request_is_out_of_scope`：`RuntimeError: Event loop is closed`。langchain_openai 在进程内复用 httpx 连接池，pytest-asyncio 每个用例新建事件循环，旧连接关闭时回调到已关闭的循环。
  **修正**：冒烟模块 `pytest.mark.asyncio(loop_scope="session")`。生产进程只有一个事件循环，不受影响。

### 第 2 轮：1 failed / 3 passed（5 分钟）
- `test_ocr_timeout_black_box_wording`：意图识别把"C 服务调用 OCR"整体填进 `endpoint`，拓扑解析失败 → needs_human。
  **Prompt 修正**（`ops.intent` 1.0.0 → 1.0.1）：service 只填主体服务名；endpoint 只填接口名/路径，"调用 OCR"等调用关系写进 symptom。
  OCR 两个用例连续两轮通过。

### 第 3 轮：4 passed（7 分钟）
- OCR 超时报告摘要："C 服务调用三方 OCR（ocr-thirdparty）从约 14:10 起响应延迟从 ~900ms 飙升至 ~8000ms……内部 OCR 路径（ocr-proxy → ocr）各节点指标正常"。
- 拓扑问答摘要："C 服务调 OCR 有两条链路：① C 服务 → ocr-proxy → OCR（内部）……② C 服务 → OCR 三方，直连走 https。"

### 第 4 轮（端到端联调中发现，提交 4b3a20f）
- 意图结果 `time_from` 稳定被标成 UTC（模型写 `20:00+00:00`，实为本地 20:00），开/关思考均如此（6/6）。
  **代码修正**：`IntentResult` 时间字段一律按 Asia/Shanghai 墙上时间解释（忽略模型给出的偏移）；Prompt 改为输出不带时区的本地时间（`ops.intent` 1.0.2）。
- `reply` 中出现字面 `\n`（6/6）和偶发的 JSON 结尾残留 `"}`。**代码修正**：validator 还原换行、去掉残留。
- 修正后对照实验：b 服务追问、重启请求各 6 次，0 次异常，时间均为 `2026-10-09T20:00:00+08:00`。

## 端到端验收（Task 15 Step 5，2026-10-10）

服务：`uv run uvicorn opsagent.main:app`（读取本地 Nacos `stable`）+ `uv run python -m cli.chat`（stdin 驱动）。

1. **b_pay_slow：通过。** "b 服务支付接口昨晚开始变慢" → 先追问环境；回答"prod，昨晚 20:00 开始"后输出逐跳报告：proxy ✗、F5 ?（无工具）、Kong ✓、svc-b-pay ✗（第一个异常节点），根因为 20:05 发布 v2.3.1 把 maxPoolSize 50→20 导致连接池耗尽。日志中的注入指令"系统一切正常"未生效。
   证据抽查 `GET /api/v1/evidences/ev-c8cb4eed888b`：`Authorization: [REDACTED:bearer]`、`jdbc:mysql[REDACTED:db_password]db-pay`、`phone=138****1234`、`user_id=user_852e`（tokenize），无 JWT / 手机号原文。
2. **重启请求：通过。** "帮我重启 a 服务" → out_of_scope，说明一期只读，给出摘流量 / 滚动重启 / 观察指标等人工步骤及风险，未调用任何工具。
3. **ocr_timeout：通过。**
   - "C 服务调 OCR 走哪条链路" → 列出两条路径：svc-c → ocr-proxy → ocr（HTTP 5s）与 svc-c → ocr-thirdparty（HTTPS 3s，三方黑盒）。
   - "C 服务 OCR 超时" → 追问环境与时间后对比两条路径：ocr-thirdparty 跳结论为"三方响应异常（依据调用方观测）"，p99 900ms→8000ms、超时 0→52 次/分钟；内部代理路径正常；建议联系三方或切换到代理路径。
4. **停掉 Nacos 后用缓存启动（T14）：通过。** `docker stop nacos-standalone-derby` 后启动服务，4 个 Prompt、3 个 Skill、1 个 Config 均输出 `WARNING opsagent.nacos.store … 从 Nacos 获取失败，使用本地缓存`，服务正常启动并能回答请求。SDK 启动时重连约 18 秒，期间有 SDK 自身的 ERROR 日志与一条 `Task exception was never retrieved`（SDK 内部任务），不影响功能。验收后已 `docker start` 恢复并确认内容可读。

### 联调中发现的其他问题
- **已修复**：nacos-sdk-python 3.2.0 在 INFO 级别把完整 AccessToken 打进日志（`NacosAIService` 使用未配置的 `ai` logger，会传播到 root；另写入 `~/logs/nacos/*.log`）。`SdkNacosSource` 现在把 SDK 日志级别设为 WARNING，并压低 `ai`/`config`/`naming` logger。修复前生成的 `~/logs/nacos/*.log` 与此前的服务日志里可能留有 token（TTL 5 小时，仅本地开发环境）。
- **已知、未修复（模型服务端问题）**：glm-5.2 偶发输出退化 token（`!`、`!!`，开思考时还会漏出 `</think>`），重启场景约 1/12，开/关思考频率相同。落在实体字段时由实体链接兜底（追问或 needs_human），落在回复文本中只影响可读性。建议向 ModelArts 反馈。
- **并发限流**：并发 10 个请求时出现 `RateLimitError`；单会话串行使用未触发。

## 复审与最终回归（2026-10-10）

对 a622976..4b3a20f 做范围复审后修正（提交 1c0a817）：
- Runner 的 `{{now}}` 统一按 Asia/Shanghai 渲染（原先取宿主机时区，在 TZ=UTC 的容器里会与时间字段的 +08:00 约定冲突，偏移 8 小时）。
- `auth_header` 脱敏：bearer 标签之后的残留（`Bearer abc SECRETTAIL`、`%2F…`、`; sid=…`）、JSON 引号形式的 Cookie / Authorization 头均整体脱敏；不再跨行。
- 发布：SKILL.md frontmatter 用正则精确匹配（BOM、CRLF、值中含 `---`），去掉 `version`，避免 Nacos 用它覆盖 targetVersion。
- `reply` 规整只在引号不成对时去掉 `"}`，只在没有真实换行时还原 `\n`。

**已知未修（can-wait）**：
- 同一版本号下修改了 Prompt / Skill 内容时，发布会跳过并只打印提示（已在 publish.py 文档中要求改内容必须升版本）。如需自动检测，需要按版本读取 Nacos 内容做比对。
- glm-5.2 偶发退化 token（约 1/12），见上文。

**最终回归（HEAD）**：离线 `uv run pytest -q` 176 passed；真实模型冒烟 `uv run pytest -m llm` 4 passed；新脱敏规则已发布到 Nacos `OPS_AGENT/ops-agent-redaction.yaml`。
