# 经营归因分析系统

## 本地后端

需要 Docker、Docker Compose、Python 3.12 和 uv。根目录 `.env` 必须配置 `LLM_API_KEY` 与 `LLM_MODEL`。变量名和其他可选设置见 `.env.example`。模型通过指定的阿里云百炼 Anthropic Messages 接口调用。后端根据模型返回的结构化计划执行分析，统计数值由 ClickHouse 和 Python 计算。

在仓库根目录依次执行以下命令。

```sh
docker compose -f docker/docker-compose.yaml up -d clickhouse
docker build -f docker/sandbox.Dockerfile -t attribution-sandbox:local .
docker build -f docker/report.Dockerfile -t attribution-report:local .
uv sync --locked
uv run python -m backend.init
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

初始化可重复执行。固定种子数据进入 ClickHouse，统计验证副本、SQLite 和本地签名密钥保存在 `.runtime/`。每个 SQLite 文件对应一个后端进程。可通过 `ATTRIBUTION_RUNTIME` 为验收使用独立状态目录。Docker 需要能够只读挂载该目录中的 DuckDB 文件。PDF 由 Docker 镜像中的 WeasyPrint 和 Noto 中文字体渲染。

启动后通过 [Swagger UI](http://127.0.0.1:8000/docs) 调试接口。以下账号用于本地演示。

| 账号 | 密码 | 权限 |
| --- | --- | --- |
| `analyst` | `analyst-demo-2025` | 两个指标域的分析、报告与审核 |
| `manager` | `manager-demo-2025` | 电商大盘、已发布报告与简报订阅 |
| `admin` | `admin-demo-2025` | 两个域的管理、审计和沙箱回放 |

## 演示与验证

- 大盘默认分析 2025 年 6 月 19–22 日，环比基期为 6 月 15–18 日。该窗口也有上一年同期和目标数据。
- 电商选择 `gmv`，观察流量、转化率和客单价贡献，再追问“按渠道下钻，只分析信息流”和“再按品类下钻，保留信息流切片”。
- 快消品输入“分析快消品净利率异常下降”，观察原料成本率与佣金费率，再追问“按品类下钻，只分析饮品”和“再按渠道下钻，保留饮品切片”。
- 完成一轮分析后可保存快照、复核假设、对比策略情景、发布报告并导出 Markdown、PDF 和 Excel。事件和检验结果会注明证据状态。
- 后端参数、领域字段与 SSE 流见 [后端接口说明](docs/backend.md)。

```sh
uv run pytest -q
ATTRIBUTION_TEST_URL=http://127.0.0.1:8000 uv run pytest -q tests/test_live_backend.py
uv run python -m backend.benchmark
```

真实接口测试会调用配置的模型并创建演示归因会话与报告。可设 `ATTRIBUTION_TEST_ARTIFACT_DIR` 保存验收导出文件。

## 本地前端

后端监听 `127.0.0.1:8000` 后，在仓库根目录运行：

```sh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

通过 Vite 输出的地址打开工作台，并使用上表中的后端账号登录。构建、测试和接口配置见[前端说明](frontend/README.md)。
