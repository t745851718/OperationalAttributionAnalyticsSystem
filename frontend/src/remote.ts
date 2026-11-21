import { references } from './formula'
import { reportSections } from './fixtures'
import { number, rounded, type Action, type Analysis, type AnalysisSummary, type Baseline, type BusinessEvent, type Conclusion, type Decomposition, type Dimension, type EventKind, type Hypothesis, type Metric, type MetricDefinition, type PivotRow, type Report, type Role, type Scenario, type Slice, type Status, type TreeNode, type User } from './model'

export type RemoteDomain = 'ecommerce' | 'fmcg'
export type RemoteDimension = Exclude<Dimension, 'date'> | 'day'
export const toDomain = (domain: string) => domain === 'all' ? undefined : domain === 'commerce' ? 'ecommerce' : domain
const fromDomain = (domain: string) => domain === 'ecommerce' ? 'commerce' : domain
export const toDimension = (dimension: Dimension): RemoteDimension => dimension === 'date' ? 'day' : dimension
const fromDimension = (dimension: RemoteDimension): Dimension => dimension === 'day' ? 'date' : dimension
const statuses: Record<string, Status> = { idle: 'idle', queued: 'running', running: 'running', complete: 'completed', failed: 'failed', cancelled: 'stopped' }
const units: Record<string, string> = { CNY: '元', ratio: '%', 'order/visit': '%', visit: '人', order: '单', 'CNY/order': '元/单', unit: '件', '1': '无量纲', '%': '%' }
const uiUnit = (unit: string) => units[unit] ?? unit
const value = (amount: number | null | undefined, unit: string): number => (amount ?? 0) * (uiUnit(unit) === '%' ? 100 : 1)
const methods: Record<string, string> = { LMDI: 'LMDI 因子拆解', cost_rate_bridge: '成本率差额拆解', difference: '差额贡献拆解', Shapley: 'Shapley 贡献拆解' }
const driverUnits: Record<string, string> = { visits: 'visit', conversion: 'order/visit', aov: 'CNY/order', materials: 'CNY', logistics: 'CNY', commission: 'CNY', revenue: 'CNY', profit: 'CNY', gross_profit: 'CNY', sales: 'CNY', orders: 'order', stockouts: 'visit', promo_orders: 'order', units: 'unit' }
const adjustable = new Set(['visits', 'conversion', 'aov', 'materials', 'logistics', 'commission'])
export const eventKinds: Record<string, EventKind> = { promotion: '大促', outage: '故障', policy: '政策', competitor: '竞品', macro: '宏观', operation: '运营' }
const titles = { overview: '异动背景与问题定义', factors: '因子贡献率拆解', drilldown: '细分维度下钻', conclusion: '核心归因结论', evidence: '统计检验与事件证据链', whatif: 'What-If 情景推演', actions: '优先行动清单' }

export const remoteUser = (user: { username: string; role: Role; domains: string[] }): User => ({ id: user.username, name: user.username, role: user.role, domains: user.domains.map(fromDomain) })

export interface RemoteDefinition {
  metric_id: string; name: string; domain_id: RemoteDomain; unit: string
  model: 'atomic' | 'add' | 'mul' | 'ratio'; type: 'atomic' | 'derived' | 'composite'
  formula: string; threshold: number; source_field?: string
}
export interface RemoteMetric extends RemoteDefinition {
  baseline_value: number | null; current_value: number | null; delta: number | null
  delta_rate: number | null; anomaly: boolean; trend: { day: string; value: number | null }[]
}
export function remoteMetric(item: RemoteMetric): Metric {
  return {
    id: item.metric_id, name: item.name, domain: fromDomain(item.domain_id), description: item.formula || item.name, unit: uiUnit(item.unit),
    previous: value(item.baseline_value, item.unit), current: value(item.current_value, item.unit), delta: value(item.delta, item.unit),
    threshold: item.threshold * 100, rate: item.delta_rate == null ? null : rounded(item.delta_rate * 100),
    mom: 0, yoy: 0, anomaly: item.anomaly, available: item.baseline_value != null && item.current_value != null, trend: item.trend.map(point => point.value === null ? null : value(point.value, item.unit)),
    dates: item.trend.map(point => point.day),
  }
}
export function remoteDefinitions(items: RemoteDefinition[]): MetricDefinition[] {
  return items.map((item, order) => ({
    id: item.metric_id, name: item.name, domain: fromDomain(item.domain_id), formula: item.formula,
    unit: uiUnit(item.unit), model: item.model === 'mul' || item.model === 'ratio' ? 'mul' : 'add',
    type: { atomic: '原子', derived: '派生', composite: '复合' }[item.type] as MetricDefinition['type'],
    parentId: items.find(parent => references(parent.formula).includes(item.metric_id))?.metric_id ?? null,
    order, wireUnit: item.unit, threshold: item.threshold, sourceField: item.source_field,
  }))
}
export function definitionBody(item: MetricDefinition) {
  const wire = item.wireUnit && uiUnit(item.wireUnit) === item.unit ? item.wireUnit : Object.keys(units).find(unit => uiUnit(unit) === item.unit) ?? item.unit
  return { metric_id: item.id || `metric_${Date.now()}`, name: item.name, domain_id: toDomain(item.domain), unit: wire, formula: item.formula.replaceAll('×', '*').replaceAll('÷', '/').replaceAll('−', '-'), threshold: item.threshold ?? .08, source_field: item.sourceField || undefined, model: item.type === '原子' ? 'atomic' : item.type === '派生' && item.formula.includes('/') ? 'ratio' : item.model }
}
type Scope = Partial<Record<RemoteDimension, string[]>>
export interface RemoteEvent { event_id: string; title: string; type: string; domain_id: RemoteDomain; start: string; end: string; scope: Scope; impact_note: string; status?: string; score?: number }
export function remoteEvent(item: RemoteEvent): BusinessEvent {
  return { id: item.event_id, title: item.title, type: eventKinds[item.type] ?? '运营', domain: fromDomain(item.domain_id), start: item.start, end: item.end, scope: Object.values(item.scope).flat(), scopeMap: item.scope, note: item.impact_note }
}
export function eventBody(item: BusinessEvent) {
  const original = item.scopeMap ?? {}
  const selection = new Set(item.scope)
  const scope = Object.fromEntries(Object.entries(original).map(([key, values]) => [key, values.filter(value => selection.has(value))]).filter(([, values]) => values.length))
  const additions = item.scope.filter(value => !Object.values(original).flat().includes(value))
  if (additions.length) {
    const dimension = item.scopeDimension ? toDimension(item.scopeDimension) : Object.keys(original)[0] ?? 'category'
    scope[dimension] = [...(scope[dimension] ?? []), ...additions]
  }
  return { domain_id: toDomain(item.domain), title: item.title, type: Object.keys(eventKinds).find(kind => eventKinds[kind] === item.type), start: item.start, end: item.end, scope, impact_note: item.note }
}

export interface RemoteSpec { metric_id: string; start: string; end: string; baseline: Baseline; dimensions: RemoteDimension[]; filters: Partial<Record<RemoteDimension, string>> }
interface RemoteNode { metric_id: string; name: string; baseline: number | null; current: number | null; children?: RemoteNode[] }
interface Factor extends RemoteNode { contribution: number }
export interface RemoteDecomposition extends RemoteNode {
  unit: string; method: string; formula: string; delta: number; delta_rate: number | null; residual: number
  factors: Factor[]; tree: RemoteNode | null; lineage?: unknown; smoothed?: boolean
}
interface RemoteHypothesis {
  hypothesis_id: string; template?: string; statement?: string; status?: string; scope?: Record<string, string>
  confidence?: number; p_value?: number; effect_size?: number; code?: unknown; sql?: string
  reasons?: string[]; difference?: number; strata_consistency?: number; elapsed_ms?: number
}
interface RemoteAction { priority: number; driver: string; action: string; owner: string; recovery_days: number; expected_recovery_cny: number; modeled_change: number }
interface RemoteRow { dimensions: Partial<Record<RemoteDimension, string>>; baseline: number | null; current: number | null; contribution: number; contribution_rate: number | null }
export interface RemoteDrill { dimensions: RemoteDimension[]; rows: RemoteRow[]; lineage: unknown }
export interface RemoteResult {
  job_id: string; data_version: string; spec: RemoteSpec; decomposition: RemoteDecomposition; drilldown: RemoteDrill
  hypotheses: RemoteHypothesis[]; events: RemoteEvent[]; actions: RemoteAction[]; summary: string
  primary_hypothesis: string | null; secondary_hypotheses: string[]
}
export interface RemoteSession {
  id: string; owner: string; domain_id: RemoteDomain; title: string; updated_at: string; status: string; spec: RemoteSpec
  result?: RemoteResult | null; job_id?: string | null
  messages?: { id: string; question: string; summary: string | null; status: string; last_event_id: number | null }[]
}
export interface RemoteScenario { id: string | null; name: string; estimate: number; delta: number; interval_80: [number, number]; changes: Record<string, number>; sensitivity_curves: Record<string, { change: number; estimate: number }[]> }
interface RemoteComment { id: string; author: string; created_at: string; section: string; quotation?: string; content: string }
export interface RemoteReport {
  id: string; session_id: string; title: string; domain_id: RemoteDomain; status: 'draft' | 'published'; version: number; updated_at: string
  payload?: { analysis: RemoteResult; scenarios: RemoteScenario[] }
}
export function remoteSummary(row: RemoteSession): AnalysisSummary {
  return { id: row.id, title: row.title, domain: fromDomain(row.domain_id), status: statuses[row.status] ?? 'idle', updatedAt: row.updated_at }
}
export function remoteScenario(row: RemoteScenario, unit: string): Scenario {
  const display = (amount: number) => unit === '%' ? amount * 100 : amount
  return { id: row.id ?? '', name: row.name, estimate: display(row.estimate), low: display(row.interval_80[0]), high: display(row.interval_80[1]), change: display(row.delta), params: Object.fromEntries(Object.entries(row.changes).map(([key, shift]) => [key, shift * 100])), curve: (Object.values(row.sensitivity_curves)[0] ?? []).map(point => [point.change * 100, display(point.estimate)]) }
}
export function remoteDecomposition(raw: RemoteDecomposition, parent?: string): Decomposition {
  const unit = raw.unit
  function tree(node: RemoteNode): TreeNode {
    const currentUnit = node.metric_id === raw.metric_id ? unit : driverUnits[node.metric_id] ?? unit
    return { id: node.metric_id, name: node.name, current: value(node.current, currentUnit), previous: value(node.baseline, currentUnit), unit: uiUnit(currentUnit), children: node.children?.map(tree) }
  }
  const factors = raw.factors
  const revenue = raw.tree?.children?.find(node => node.metric_id === 'revenue')
  const profitRevenue = raw.tree?.children?.flatMap(node => node.children ?? []).find(node => node.metric_id === 'revenue')
  const revenueNode = revenue ?? profitRevenue
  return {
    tree: tree(raw.tree ?? raw), previous: value(raw.baseline, unit), current: value(raw.current, unit), residual: raw.residual,
    method: (methods[raw.method] ?? raw.method) + (raw.smoothed ? ' · 零值平滑' : ''),
    sql: JSON.stringify(raw.lineage ?? { formula: raw.formula }, null, 2),
    drivers: factors.map(factor => {
      const costRate = parent === 'fmcg' && ['materials', 'logistics', 'commission'].includes(factor.metric_id) && revenueNode?.current && revenueNode.baseline
      const source = costRate ? 'ratio' : driverUnits[factor.metric_id] ?? unit
      return { id: factor.metric_id, name: factor.name, previous: value(costRate ? (factor.baseline ?? 0) / revenueNode.baseline! : factor.baseline, source), current: value(costRate ? (factor.current ?? 0) / revenueNode.current! : factor.current, source), unit: uiUnit(source), value: value(factor.contribution, unit), adjustable: adjustable.has(factor.metric_id), sensitivity: 0, min: -20, max: 20 }
    }),
  }
}
export function remoteSlices(spec: RemoteSpec): Slice[] {
  return Object.entries(spec.filters).map(([key, value]) => ({ dimension: fromDimension(key as RemoteDimension), value }))
}
export function remoteHypothesis(item: RemoteHypothesis, previous?: Hypothesis): Hypothesis {
  const labels: Record<string, Hypothesis['status']> = { verifying: 'pending', supported: 'confirmed', excluded: 'excluded', insufficient_data: 'insufficient', timeout: 'timeout', error: 'failed' }
  const code = item.code ?? (item.sql ? item : undefined)
  return {
    id: item.hypothesis_id, statement: item.statement ?? previous?.statement ?? '正在验证统计假设', driver: Object.values(item.scope ?? {}).join(' · ') || previous?.driver || '统计验证',
    status: labels[item.status ?? ''] ?? previous?.status ?? 'pending', confidence: item.confidence ?? previous?.confidence ?? null, p: item.p_value ?? previous?.p ?? null, effect: item.effect_size ?? previous?.effect ?? null,
    code: code ? JSON.stringify(code, null, 2) : previous?.code ?? '',
    output: [item.difference != null ? `检验口径差 ${number(item.difference)}` : '', item.strata_consistency != null ? `分层一致性 ${number(item.strata_consistency * 100, '%')}` : '', ...item.reasons ?? []].filter(Boolean).join('。') || previous?.output || '',
    elapsed: item.elapsed_ms ?? previous?.elapsed ?? null,
  }
}
export function withResult(session: Analysis, raw: RemoteResult): Analysis {
  const { spec, decomposition } = raw
  const unit = uiUnit(decomposition.unit)
  const previous = value(decomposition.baseline, decomposition.unit)
  const current = value(decomposition.current, decomposition.unit)
  const metric: Metric = {
    id: decomposition.metric_id, name: decomposition.name, domain: session.domain, description: decomposition.formula || decomposition.name, unit, previous, current,
    delta: current - previous, rate: decomposition.delta_rate == null ? null : decomposition.delta_rate * 100, threshold: 0, mom: 0, yoy: 0,
    trend: raw.drilldown.dimensions.includes('day') ? [...raw.drilldown.rows].sort((a, b) => (a.dimensions.day ?? '').localeCompare(b.dimensions.day ?? '')).map(row => row.current === null ? null : value(row.current, decomposition.unit)) : [],
  }
  const hypotheses = raw.hypotheses.map(item => remoteHypothesis(item))
  const conclusions: Conclusion[] = hypotheses.filter(item => item.id === raw.primary_hypothesis || raw.secondary_hypotheses.includes(item.id)).map(item => ({
    id: item.id, title: item.statement, text: item.output, type: item.id === raw.primary_hypothesis ? '首要原因' : '次要原因',
  }))
  if (raw.summary) conclusions.unshift({ id: 'summary', title: '经营归因摘要', text: raw.summary, type: '首要原因' })
  for (const event of raw.events) conclusions.push({ id: event.event_id, title: event.title, text: `${event.status === 'consistent_with_evidence' ? '与检验证据一致' : '候选解释'} · ${event.impact_note}`, eventId: event.event_id, type: '外部事件' })
  const actions: Action[] = raw.actions.map(item => ({ id: item.driver, title: item.action, description: `建议调整 ${number(item.modeled_change * 100, '%', true)}`, driver: decomposition.factors.find(factor => factor.metric_id === item.driver)?.name ?? item.driver, owner: item.owner, days: item.recovery_days, recovery: item.expected_recovery_cny }))
  return { ...session, metric, period: { start: spec.start, end: spec.end }, baseline: spec.baseline, dimension: fromDimension(spec.dimensions[0]), slices: remoteSlices(spec), decomposition: remoteDecomposition(decomposition, session.domain), hypotheses, conclusions, events: raw.events.map(remoteEvent), actions }
}
export function remoteSession(row: RemoteSession, cases: RemoteScenario[] = []): Analysis {
  const jobs = row.messages ?? []
  const latest = jobs.at(-1)
  const summary = remoteSummary(row)
  const spec = row.spec
  const state: Analysis = {
    ...summary, title: row.title + '归因', period: { start: spec.start, end: spec.end }, baseline: spec.baseline,
    metric: null, status: summary.status, step: summary.status === 'completed' ? 7 : 0, eventId: 0, jobId: row.job_id ?? latest?.id,
    messageCount: jobs.length, messages: jobs.flatMap(job => [{ id: job.id, role: 'user' as const, text: job.question }, ...(job.summary ? [{ id: job.id + '-summary', role: 'assistant' as const, text: job.summary }] : [])]),
    hypotheses: [], conclusions: [], actions: [], events: [], dimension: fromDimension(spec.dimensions[0]), slices: remoteSlices(spec), decomposition: null, scenarios: [],
  }
  const result = row.result ? withResult(state, row.result) : state
  result.scenarios = cases.map(item => remoteScenario(item, result.metric?.unit ?? ''))
  return result
}
export function remoteRows(drill: RemoteDrill, primary: Dimension, unit: string): PivotRow[] {
  const key = toDimension(primary)
  const display = (amount: number | null) => amount == null ? null : amount * (unit === '%' ? 100 : 1)
  return drill.rows.map((row, index) => {
    const secondary = drill.dimensions.find(item => item !== key)
    const label = row.dimensions[key] ?? '全部'
    return { id: `${key}-${index}`, label: secondary ? `${label} / ${row.dimensions[secondary] ?? '全部'}` : label, dimension: primary, previous: display(row.baseline), current: display(row.current), delta: display(row.contribution) ?? 0, contribution: row.contribution_rate == null ? null : row.contribution_rate * 100 }
  })
}
export function remoteReport(raw: RemoteReport, comments: RemoteComment[] = [], subscribed = false): Report {
  const payload = raw.payload
  const report: Report = { id: raw.id, sessionId: raw.session_id, title: raw.title, domain: fromDomain(raw.domain_id), version: raw.version, status: raw.status, updatedAt: raw.updated_at, sections: [], subscribed,
    comments: comments.map(item => ({ id: item.id, author: item.author, createdAt: item.created_at, section: item.section, quote: item.quotation, text: item.content })) }
  if (payload) {
    const row = { id: raw.session_id, owner: '', title: raw.title, domain_id: raw.domain_id, updated_at: raw.updated_at, status: 'complete', spec: payload.analysis.spec, result: payload.analysis }
    const analysis = remoteSession(row, payload.scenarios)
    const data = remoteRows(payload.analysis.drilldown, analysis.dimension, analysis.metric?.unit ?? '').slice(0, 20)
    report.sections = reportSections(analysis, data).map(section => {
      const id = (section.id === 'drivers' ? 'factors' : section.id === 'drill' ? 'drilldown' : section.id) as keyof typeof titles
      return { ...section, id, title: titles[id] }
    })
  }
  return report
}
export type { RemoteComment }
