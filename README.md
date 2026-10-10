# ops-agent

运维 AI Agent（一期端到端细线）。设计见 `运维AI_Agent开发设计文档_v2_MVP.md` 和 `docs/superpowers/specs/`。

## 准备

```bash
brew install uv && uv python install 3.12
uv sync
cp .env.example .env        # 填写 OPSAGENT_LLM_API_KEY、OPSAGENT_NACOS_PASSWORD
docker compose up -d        # PostgreSQL（含测试库 opsagent_test）
uv run python -m opsagent.storage.init_db
uv run python -m opsagent.topology.load fixtures/topology.yaml
uv run python -m nacos_seed.publish --label stable   # 发布 Prompt / Skill / 脱敏规则到本地 Nacos
```

没有 Nacos 时，可以在 `.env` 中设置 `OPSAGENT_NACOS_MODE=seed`，直接读取 `nacos_seed/` 目录。

## 运行

```bash
uv run uvicorn opsagent.main:app --host 127.0.0.1 --port 8000
uv run python -m cli.chat
```

mock 场景通过 `OPSAGENT_MOCK_SCENARIO` 切换：`b_pay_slow`（b 服务支付接口变慢）或 `ocr_timeout`（三方 OCR 超时）。

## 测试

```bash
uv run pytest               # 单元测试 + 图测试 + 数据库测试（需要 docker compose）
uv run pytest -m llm -v -s  # 真实模型冒烟测试（需要 API Key）
```

## 修改 Prompt / Skill

编辑 `nacos_seed/` → `uv run pytest -m llm` 验证 → `uv run python -m nacos_seed.publish --label gray` 发布灰度版本 → 确认后用 `--label stable` 发布。运行中的服务每 60 秒拉取一次新版本。
