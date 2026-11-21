export type Role = 'analyst' | 'manager' | 'admin'
export type Baseline = 'mom' | 'yoy' | 'target'
export type Status = 'idle' | 'running' | 'completed' | 'stopped' | 'failed'
export type Dimension = 'channel' | 'region' | 'category' | 'segment' | 'date'
export type EventKind = '大促' | '故障' | '政策' | '竞品' | '宏观' | '运营'
export type Format = 'md' | 'pdf' | 'xlsx'

export interface User { id: string; name: string; role: Role; domains: string[] }
export interface Period { start: string; end: string }
export interface Filter extends Period { domain: string; baseline: Baseline }
export interface Metric {
  id: string; name: string; description: string; domain: string; unit: string
  current: number; previous: number; delta: number; rate: number | null
  threshold: number; mom: number; yoy: number; trend: (number | null)[]; dates?: string[]; anomaly?: boolean; available?: boolean
}
export interface Driver {
  id: string; name: string; value: number; previous: number; current: number
  unit: string; adjustable: boolean; sensitivity: number; min: number; max: number
}
export interface TreeNode { id: string; name: string; current: number; previous: number; unit: string; children?: TreeNode[] }
export interface Slice { dimension: Dimension; value: string }
export interface PivotRow { id: string; label: string; dimension: Dimension; previous: number | null; current: number | null; delta: number; contribution: number | null; children?: PivotRow[] }
export interface BusinessEvent extends Period { id: string; title: string; domain: string; type: EventKind; scope: string[]; note: string; scopeMap?: Record<string, string[]>; scopeDimension?: Dimension }
export interface Hypothesis {
  id: string; statement: string; driver: string; status: 'pending' | 'confirmed' | 'excluded' | 'insufficient' | 'timeout' | 'failed'
  confidence: number | null; p: number | null; effect: number | null; code: string; output: string; elapsed: number | null
}
export interface Conclusion { id: string; title: string; text: string; type: '首要原因' | '次要原因' | '外部事件'; eventId?: string }
export interface Action { id: string; title: string; description: string; driver: string; owner: string; days: number; recovery: number }
export interface Scenario { id: string; name: string; params: Record<string, number>; estimate: number; low: number; high: number; change: number; curve: [number, number][] }
export interface Message { id: string; role: 'user' | 'assistant'; text: string }
export interface Decomposition { drivers: Driver[]; tree: TreeNode; previous: number; current: number; residual: number; method: string; sql: string }
export interface Analysis {
  id: string; title: string; metric: Metric | null; period: Period; baseline: Baseline; domain: string
  status: Status; step: number; jobId?: string; eventId: number; messageCount: number; updatedAt: string
  messages: Message[]; hypotheses: Hypothesis[]; conclusions: Conclusion[]; actions: Action[]
  events: BusinessEvent[]; slices: Slice[]; dimension: Dimension; decomposition: Decomposition | null
  scenarios: Scenario[]; error?: string
}
export interface AnalysisSummary { id: string; title: string; status: Status; updatedAt: string; domain: string }
export interface NewAnalysis { question?: string; metricId?: string; period: Period; baseline: Baseline; domain: string }
export interface StreamEvent { id: number; type: 'plan' | 'step' | 'code' | 'hypothesis' | 'conclusion' | 'done' | 'stopped' | 'error'; analysis: Analysis }
export interface MetricDefinition { id: string; name: string; domain: string; unit: string; type: '原子' | '派生' | '复合'; model: 'add' | 'mul'; formula: string; parentId: string | null; order: number; threshold?: number; wireUnit?: string; sourceField?: string }
export interface ReportSection { id: string; title: string; paragraphs: string[]; headers?: string[]; rows?: (string | number)[][] }
export interface Comment { id: string; author: string; section: string; quote?: string; text: string; createdAt: string }
export interface Report { id: string; sessionId: string; title: string; domain: string; version: number; status: 'draft' | 'published'; updatedAt: string; sections: ReportSection[]; comments: Comment[]; subscribed?: boolean }

export const domains = [
  { id: 'all', label: '全部业务线' }, { id: 'commerce', label: '电商零售' }, { id: 'fmcg', label: '快消品' },
]
export const dimensions: Record<Dimension, string> = { channel: '渠道', region: '区域', category: '品类', segment: '客群', date: '时间' }
export const roleLabels: Record<Role, string> = { analyst: '经营分析师', manager: '业务负责人', admin: '数据管理员' }
export const baselineLabels: Record<Baseline, string> = { mom: '环比', yoy: '同比', target: '目标差' }
export const demoPeriod = { start: '2025-06-23', end: '2025-06-29' }
export const steps = ['识别异动', '指标拆解', '维度下钻', '假设生成', '统计检验', '业务归因', '策略建议']
export const domainLabel = (id: string) => domains.find(domain => domain.id === id)?.label ?? id
export const rounded = (value: number, precision = 2) => Number(value.toFixed(precision))

export function number(value: number | null | undefined, unit = '', signed = false) {
  if (value == null) return '—'
  const prefix = signed && value > 0 ? '+' : ''
  const formatted = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: unit === '元' ? 0 : 2 }).format(value)
  if (unit === '元') return `${prefix}${value < 0 ? '−' : ''}¥${formatted.replace('-', '')}`
  return `${prefix}${formatted}${unit}`
}

export const newId = () => crypto.randomUUID()
