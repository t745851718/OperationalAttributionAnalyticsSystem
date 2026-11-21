# 后端接口与数据口径

## 认证与指标域

除健康检查、元数据和 API 文档外，请求使用 `Authorization: Bearer <access_token>`。`POST /api/auth/login` 接受 `username` 和 `password`，返回令牌和 `user.username`、`user.role`、`user.domains`。内置数据域为 `ecommerce` 和 `fmcg`。在大盘、会话、事件和归档列表使用可选的 `domain_id` 参数。管理员可调整业务线名称和说明。

`GET /api/meta` 返回演示日期、对比基期和维度 ID。五个下钻维度为 `day`、`channel`、`region`、`category`、`segment`。数值使用原始单位，小数比例 `0.05` 表示 5%。`mom` 为紧邻同长度日期区间，`yoy` 为上年同期，`target` 为同日期的目标数据。`GET /api/dashboard/metrics` 接受 `start`、`end`、`baseline`，返回 `metrics`、`attention` 和统计区间。

## 会话和任务

`POST /api/sessions` 接收指标 ID 或自然语言问题，可附上日期和基期。默认自动启动分析。

```json
{"metric_id":"gmv","domain_id":"ecommerce","start":"2025-06-19","end":"2025-06-22","baseline":"mom"}
```

```json
{"domain_id":"fmcg","question":"分析快消品净利率异常下降"}
```

响应中的 `id` 为会话 ID，`job_id` 和 `stream_url` 用于订阅任务。`GET /api/sessions/{id}` 返回分析规格、最新成功结果、历史提问及其任务 ID、进度状态与事件游标。`POST /api/sessions/{id}/messages` 接受 `{"content":"按渠道下钻，只分析信息流"}`，直接返回 SSE。可附 `Idempotency-Key` 重放同一请求。单会话同时运行一个任务。

`GET /api/jobs/{id}/events` 通过 `Last-Event-ID` 或 `after` 重放比游标更新的消息。使用支持 Bearer 请求头的流式客户端。响应包含 `X-Analysis-Job-Id`。客户端断开后任务继续运行，进程重启后读取 SQLite 检查点。

| SSE 事件 | 内容 |
| --- | --- |
| `plan` | 排队事件含步骤清单，规划完成事件含解析后的 `spec` 和待检假设 |
| `step` | 步骤索引、说明与执行状态 |
| `code` | 统计验证 SQL、应用到各窗口的绑定参数和执行器 |
| `hypothesis` | 验证进度、执行耗时、结果、置信度和排除原因 |
| `conclusion` | 指标拆解、维度贡献、事件、证据、结论和建议 |
| `complete`、`failed`、`cancelled` | 任务终态，失败事件附错误说明 |

用 `POST /api/jobs/{id}/cancel` 停止任务。用 `POST /api/jobs/{id}/retry` 重试会话中最近失败的任务并保留通过的检查点。分析师可用 `PUT /api/jobs/{id}/hypotheses/{hypothesis_id}/review` 保存审核意见。

## 分析、推演和报告

- `GET /api/sessions/{id}/decomposition` 返回因子贡献、瀑布图起止值、指标树、差额残差、真实口径和参数化 SQL。`GET /api/sessions/{id}/drilldown?dim=channel&dim=category` 支持组合维度，返回桶贡献及维度 Shapley 分解。总差额为零时贡献率返回 `null`。
- `POST /api/sessions/{id}/whatif` 接受 `{"name":"流量恢复","changes":{"visits":0.05},"save":true}`。可调电商驱动为 `visits`、`conversion`、`aov`，快消品成本率驱动为 `materials`、`logistics`、`commission`。返回点估计、80% bootstrap 区间、灵敏度曲线和预期金额。同一公式构成恒等式时，区间可能收敛到点估计。用 `GET /api/sessions/{id}/scenarios` 列出保存的情景。
- `POST /api/sessions/{id}/snapshots` 保存分析快照。`POST /api/sessions/{id}/report` 生成有版本的报告，可选 `title`。`PATCH /api/reports/{id}` 设置 `{"status":"published"}`。`GET /api/reports/{id}/preview` 返回可打印 HTML。`GET /api/reports/{id}/export?fmt=md|pdf|xlsx` 支持重复传入 `section` 缩小章节范围。段落批注和提及通过 `/api/reports/{id}/comments` 维护。
- `/api/events` 和 `/api/metrics` 支持列表和创建。以对应 ID 发起 `PUT` 或 `DELETE` 更新或删除。管理员使用 `/api/admin/settings` 管理统计置信度、模型输出预算、沙箱配额和本地 ClickHouse 数据源。数据源必须存在同一数据版本和事实表。
- `GET /api/admin/audit` 查询审计记录。`POST /api/sandbox/run?audit_id=<id>` 回放保存的验证。分析师和管理员写入数据需有对应指标域权限。负责人只能查看授权域内的已发布报告，并通过 `/api/subscriptions` 和 `/api/digests` 使用站内简报。

## 计算与隔离

GMV 使用 LMDI，净利率按费用占营收比率桥接，普通加法使用有符号差额。多维 Shapley 在四维及以下精确枚举维度组合，超过四维采用固定种子抽样。透视行的桶贡献另按事实桶数选择精确枚举或抽样，保留差额总和。

模型接收授权域内的指标定义、允许的维度值及需要解释的证据状态。验证代码由服务端选择已登记的 SQL 和统计模板，输入采用绑定参数，复现信息落库。统计容器使用只读 DuckDB 副本、无网络、只读文件系统和资源限制。模型或沙箱不可用时，接口保留检查点并返回明确错误。

业务事件按前后 3 日窗口和影响维度匹配。证据区区分候选事件和与检验一致的事件。模拟和事件匹配用于辅助经营判断，报告记录检验数据、口径和局限。
