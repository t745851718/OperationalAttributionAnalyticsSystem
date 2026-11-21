# 经营归因分析系统

## 本地后端

需要 Docker、Docker Compose、Python 3.12 和 uv。根目录 `.env` 必须配置 `LLM_API_KEY` 与 `LLM_MODEL`。变量名和其他可选设置见 `.env.example`。模型通过指定的阿里云百炼 Anthropic Messages 接口调用。后端根据模型返回的结构化计划执行分析，统计数值由 ClickHouse 和 Python 计算。

首次安装时，在仓库根目录依次执行以下命令。已有 SQLite 数据的实例请按下方迁移步骤操作。

```sh
docker compose --env-file .env -f docker/docker-compose.yaml up -d --wait postgres clickhouse
docker compose --env-file .env -f docker/docker-compose.yaml build sandbox report
uv sync --locked
uv run python -m backend.init
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

ClickHouse 就绪后即可初始化数仓。统计沙箱和 PDF 镜像由同一个 Compose 文件构建，后端收到分析或导出请求时启动一次性容器。

初始化可重复执行。Docker 使用 `postgres:18`，命名卷 `postgres_data` 挂载到 `/var/lib/postgresql`。API 默认连接 `127.0.0.1:5432/attribution`。`.env.example` 列出本地连接参数。可用 `DATABASE_URL` 单独指定 API 的目标库。每个应用 schema 运行一个 API 进程，PostgreSQL 会话级锁用于协调任务恢复。

ClickHouse 保存经营事实数据。`ATTRIBUTION_RUNTIME` 指定 DuckDB 只读验证副本和本地签名密钥目录，默认是 `.runtime/`。Docker 需要能挂载此目录中的 DuckDB 文件。PDF 由报告镜像中的 WeasyPrint 和 Noto 中文字体渲染。

### 从 SQLite 迁移历史数据

停止旧 API，保留原 `.runtime/`，在空的 PostgreSQL 应用库上执行以下命令。请在导入后再运行示例数据初始化，以免提前填充目标表。

```sh
docker compose --env-file .env -f docker/docker-compose.yaml up -d --wait postgres clickhouse
docker compose --env-file .env -f docker/docker-compose.yaml build sandbox report
uv sync --locked
uv run python -m backend.migrations.from_sqlite .runtime/app.sqlite3
uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

导入器只读打开源数据库，在同一事务中复制 15 张业务表，检查各表行数，并续接任务事件和审计序号。遇到非空目标表时会回滚导入。已经初始化过数仓的实例可直接复用原 ClickHouse、DuckDB 和签名密钥。

### 项目目录

| 目录 | 职责 |
| --- | --- |
| `backend/models/` | PostgreSQL 表结构、存储访问、领域模型、指标公式和数仓查询 |
| `backend/controllers/` | FastAPI 路由、权限检查、会话和管理接口 |
| `backend/services/` | 模型调用、归因计算、任务调度、统计沙箱和简报 |
| `backend/views/` | 报告 HTML 预览与 Markdown、PDF、Excel 渲染 |
| `frontend/src/pages/`、`components/` | Vue 页面与交互视图 |
| `backend/migrations/` | 历史应用库迁移工具 |

`backend/main.py` 负责组装应用和管理服务生命周期。

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

任务测试需要 PostgreSQL，并在独立的临时 schema 中验证恢复和重试。真实接口测试会调用配置的模型并创建演示归因会话与报告。可设 `ATTRIBUTION_TEST_ARTIFACT_DIR` 保存验收导出文件。

## 本地前端

后端监听 `127.0.0.1:8000` 后，在仓库根目录运行：

```sh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

通过 Vite 输出的地址打开工作台，并使用上表中的后端账号登录。构建、测试和接口配置见[前端说明](frontend/README.md)。
