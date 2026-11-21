# 经营归因分析系统 · spec.md

> 所属：其他项目 2.1 ｜ 交付目录命名：`组名_姓名_经营归因_行业`

## 1. 项目目标与交付形式
面向企业核心经营场景的**智能多维归因分析系统**：围绕指标异常波动，结合指标树因子拆解、自动假设生成、统计检验验证与业务大事件因果关联，支持多轮下钻追问、What-If 反事实仿真与归因报告导出，输出带量化贡献率与落地策略的经营洞察。

交付：三栏交互式归因工作台（前端）｜后端服务（含统计检验与代码沙箱执行器）｜示例多维数仓数据集｜大促与经营异动仿真案例｜多格式报告导出（Markdown/PDF/Excel）｜完整演示链路。

## 2. 用户角色与权限
| 角色 | 权限要点 |
| --- | --- |
| 经营分析师 | 创建会话、设定目标指标、追问、调优拆解逻辑、审核证据链、调整 What-If、发布与导出报告 |
| 业务负责人/管理层 | 查看异动大盘、结构化结论与贡献率、行动项；订阅周期简报；只读 |
| 系统与数据管理员 | 维护指标元数据与公式、数据源、事件日历、模型参数与沙箱配额 |

基础能力：统一认证登录（JWT）、多指标域/业务线管理、多轮会话管理、数据源接入、操作审计与运行日志。

## 3. 功能模块
| 模块 | 功能 |
| --- | --- |
| 指标体系与公式引擎 | 原子/派生/复合指标；层级指标树；加法与乘法模型的动态代数分解 |
| 意图理解与规划调度 | 解析目标指标、时间范围、对比基期（同比/环比/目标差）；规划步骤：识别异动→指标拆解→维度下钻→假设生成→统计检验→业务归因→策略建议 |
| 安全数据分析沙箱 | 只读数据查询 + 受限 Python/SQL 执行；运行 LMDI、假设检验；资源配额 |
| 因果关联与知识引擎 | 业务事件日历检索、历史归因库、事件-指标相关度、因果解释链 |
| 敏感性模拟与建议引擎 | 弹性系数、历史波动率、多情景推演、优先建议 |
| 会话状态与报告管理 | 多轮上下文、中间快照持久化、报告结构化落库与导出 |

## 4. 归因方法论与规则
**4.1 贡献率测算**
- 加法模型（利润=营收−成本）：差额分析，`ΔY=Σ Δx_i`，贡献率 `c_i=Δx_i/ΔY`。
- 乘法模型（销售额=访客×转化率×客单价）：**LMDI**。`Y=Πx_i`，`ΔY_i = L(Y¹,Y⁰)·ln(x_i¹/x_i⁰)`，`L(a,b)=(a−b)/(ln a−ln b)`（a=b 时取 a）。要求 `ΣΔY_i = Y¹−Y⁰`（严格守恒，残差=0，单测断言容差 1e-9）。基期/现期为 0 时使用 δ=1e-9 平滑并标注。
- 杜邦分析：ROE=净利率×周转率×权益乘数，复用乘法分解。
- 维度下钻：占比贡献 `ΔV_j/ΔV_total`；多维交叉使用 Shapley 值（维度数 ≤4 精确枚举，超出采样近似），贡献率之和=100%。

**4.2 假设生成与双向验证**
- 依据因子异动幅度并行生成 3~5 条候选假设（示例："高流量低转化渠道占比提升导致转化率下滑"、"某品类断货导致客单价下降"）。
- 每条假设必须产出**可执行探查代码**，在沙箱中执行，输出：量化事实、效应量、p 值、置信度（综合显著性、效应量、贡献覆盖率，范围 0~1）。
- 置信度 < 阈值（默认 0.6，可配）→ 标记"已排除"。
- 伪相关排除：分层一致性（Simpson 悖论检查）、偏相关（控制时间趋势与季节项）、时间先后性检验；不通过则降级并记录原因。

**4.3 业务大事件关联**：以异动窗口 ±3 日匹配事件日历；时间、品类、渠道任一维度重合即计算相关度（时间重叠×维度重叠），超过阈值作为外生解释变量写入因果链，避免误判为内部操作问题。

**4.4 落地策略**：每条建议必须绑定量化驱动因子，含责任角色、预期恢复周期、预期挽回金额；无依据的泛化建议一律拒绝输出（后端校验 schema）。

**4.5 What-If**：用历史数据回归估计弹性系数 `e=%ΔY/%Δx`，区间用 bootstrap（1000 次）；输出点估计+80% 区间，支持多情景对比。

**4.6 沙箱安全**：只读数仓副本（DuckDB/SQLite）；Python 子进程，白名单库（pandas/numpy/scipy/statsmodels），禁网络与文件写；CPU 20s、内存 512MB、输出 1MB；SQL 仅 SELECT；所有代码与结果入审计。

## 5. 数据模型（核心）
| 表 | 关键字段 |
| --- | --- |
| metric_def | metric_id, name, type(原子/派生/复合), formula, model(add/mul), unit, domain_id |
| metric_tree | node_id, metric_id, parent_id, level, op(+,−,×,÷) |
| dim_def | dim_id, name(时间/渠道/区域/品类/客群), hierarchy_json |
| biz_event | event_id, type(大促/故障/政策/竞品/宏观), title, start, end, scope_dim_json, impact_note |
| analysis_session | session_id, user_id, target_metric, period, baseline(同比/环比/目标), status, created_at |
| session_message | msg_id, session_id, role, content, plan_json, created_at |
| decomposition_result | id, session_id, metric_id, method, factors_json(Δ/贡献率), residual |
| hypothesis | hyp_id, session_id, statement, code, result_json, p_value, effect_size, confidence, status(待验证/成立/已排除) |
| evidence | evidence_id, hyp_id, type(表/图/代码/事件), payload_json |
| whatif_scenario | scenario_id, session_id, params_json, result_json |
| report | report_id, session_id, version, content_md, status, exported_files |
| audit_log | log_id, user_id, action, target, detail, created_at |

示例数仓（星型）：`fact_orders / fact_traffic_funnel / fact_cost / fact_subscription`；维表 `dim_date / dim_channel / dim_region / dim_category / dim_customer_segment`；事件表 `biz_event`。

## 6. 核心接口
| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/auth/login | 登录 |
| GET | /api/dashboard/metrics | 指标大盘（含异常标识） |
| POST | /api/sessions | 新建归因会话（可由大盘一键发起） |
| POST | /api/sessions/{id}/messages | 追问（SSE：plan/step/code/hypothesis/conclusion） |
| GET | /api/sessions/{id}/decomposition | 因子拆解与瀑布数据 |
| GET | /api/sessions/{id}/drilldown?dim= | 维度下钻透视 |
| POST | /api/sandbox/run | 沙箱执行（内部/调试） |
| GET/POST | /api/events | 业务事件日历 CRUD |
| GET/POST | /api/metrics | 指标字典 CRUD |
| POST | /api/sessions/{id}/whatif | What-If 推演 |
| POST | /api/sessions/{id}/report | 生成报告；GET `/api/reports/{id}/export?fmt=md|pdf|xlsx` |

## 7. 核心业务流程
1. **发起**：大盘发现异常或自然语言发起 → 解析指标/时间/基期 → 读取指标树完成一级因子拆解与拉动率。
2. **验证**：生成 3~5 条假设 → 沙箱并行下钻验证 → 过滤无关假设 → 匹配事件日历补全因果链。
3. **追问**：继承前序上下文，锁定异常切片，向下钻取细分指标与行为数据，刷新证据链。
4. **推演与报告**：锁定可干预因子 → What-If 调参 → 汇总生成报告并导出。

## 8. 报告结构
异动背景与问题定义（指标/周期/基期值/现期值/差异额/差异率）｜因子贡献率拆解（瀑布图+表）｜细分维度下钻证据（TOP 维度组合+透视表）｜核心归因结论（首要/次要/内外部诱因）｜因果证据链与置信度（代码结果、显著性）｜What-If 结论｜落地行动清单（动作/责任岗位/周期/预期收益）。

## 9. 示例数据与演示场景（至少完成两个）
- **电商 GMV 下滑**：订单、商品、类目、流量与转化漏斗、促销活动表；注入"大促后流量回落 + 高流量低转化渠道占比上升 + 某品类断货"。
- **快消品利润率异动**：营收、原材料成本、物流履约、渠道佣金；注入"原料涨价 + 渠道佣金调整"。
- **SaaS 订阅续约率**（可选）：客户分层、功能活跃日志、工单、销售跟进。
- 数据用固定种子生成，附期望归因结果（用于验收断言）。

## 10. 非功能要求
- LMDI/Shapley 分解 10 万行聚合数据 < 3s；单次沙箱验证 < 20s；首个流式事件 < 2s。
- 结果可复现：保存 SQL/代码/参数/数据版本；LLM 仅负责规划与文字解释，**所有数字由确定性计算产生**。
- 全程审计；越权数据域不可见。

## 11. 验收标准
- [ ] 大盘或工作台可发起归因会话
- [ ] 复合指标多级拆解，贡献率总和守恒（瀑布图收敛到总变动）
- [ ] 自动生成假设并经沙箱量化验证，低置信度标记"已排除"，伪相关被识别
- [ ] 三栏工作台多轮追问保持上下文并刷新证据链
- [ ] 事件日历自动匹配并写入因果链
- [ ] What-If 调参实时重算并支持情景对比
- [ ] 报告含量化证据、因果结论、优先级策略，导出 PDF/Excel/Markdown 成功
- [ ] 至少两组预置场景完整闭环

## 12. 技术栈与目录
后端 Python/FastAPI、ClickHouse、pandas/scipy/statsmodels；前端 Vue 3 + ECharts（瀑布/桑基/树图）；导出：WeasyPrint 或 Playwright（PDF）、openpyxl（Excel）。

```
├─ backend/ (api, planner, decomposer, sandbox, causal, simulator, report)
├─ frontend/ (workbench, dashboard, events, dictionary, reports)
├─ data/ (generators/, warehouse.duckdb, events.csv, expected_attribution.json)
├─ docs/ screenshots/  spec.md ui.md README.md
```
