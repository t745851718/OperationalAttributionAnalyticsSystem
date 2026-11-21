import { analysisEvidence, attribution, fixtureDefinitions, fixtureEvents, metricList, pivotRows, reportSections } from './fixtures'
import { demoPeriod, dimensions, newId, rounded, steps, type Analysis, type AnalysisSummary, type BusinessEvent, type Comment, type Dimension, type Filter, type Format, type Metric, type MetricDefinition, type NewAnalysis, type PivotRow, type Report, type Role, type Scenario, type Slice, type StreamEvent, type User } from './model'

import { definitionBody, eventBody, remoteDecomposition, remoteDefinitions, remoteEvent, remoteHypothesis, remoteMetric, remoteReport, remoteRows, remoteScenario, remoteSession, remoteSlices, remoteSummary, remoteUser, toDimension, toDomain, withResult, type RemoteComment, type RemoteDecomposition, type RemoteDefinition, type RemoteDrill, type RemoteEvent, type RemoteMetric, type RemoteReport, type RemoteResult, type RemoteScenario, type RemoteSession, type RemoteSpec } from './remote'

export const demoMode = import.meta.env.VITE_DATA_MODE === 'fixture'
export const dataPeriod = demoMode ? demoPeriod : { start: '2025-06-19', end: '2025-06-22' }
const namespace = demoMode ? 'attribution.v1.' : 'attribution.api.v1.'
const read = <T>(key: string, fallback: T): T => {
  try {
    const value = localStorage.getItem(namespace + key)
    return value === null ? fallback : JSON.parse(value) as T
  } catch { return fallback }
}
const write = <T>(key: string, value: T): T => {
  localStorage.setItem(namespace + key, JSON.stringify(value))
  return value
}

interface Identity { user: User; token?: string }
export const getIdentity = () => read<Identity | null>('identity', null)
export const setIdentity = (identity: Identity | null) => write('identity', identity)
export const demoUsers: User[] = [
  { id: 'analyst', name: '林晓', role: 'analyst', domains: ['commerce', 'fmcg'] },
  { id: 'manager', name: '周宁', role: 'manager', domains: ['commerce', 'fmcg'] },
  { id: 'admin', name: '陈越', role: 'admin', domains: ['commerce', 'fmcg'] },
]

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message) }
}
function requireUser(domain?: string, roles?: Role[]) {
  const { user } = getIdentity() ?? {}
  if (!user) throw new ApiError('请先登录。', 401)
  if ((domain && domain !== 'all' && !user.domains.includes(domain)) || (roles && !roles.includes(user.role))) {
    throw new ApiError('当前角色没有执行此操作的权限。', 403)
  }
  return user
}

const sessions = () => read<Analysis[]>('sessions', [])
const reports = () => read<Report[]>('reports', [])
const calendar = () => read('events', fixtureEvents)
const definitions = () => read('definitions', fixtureDefinitions)

function saveItem<T extends { id: string }>(key: string, items: T[], item: T) {
  write(key, [item, ...items.filter(entry => entry.id !== item.id)])
  return item
}
function find<T extends { id: string }>(items: T[], id: string): T {
  const item = items.find(entry => entry.id === id)
  if (!item) throw new ApiError('这条记录已不存在。', 404)
  return item
}
function findSession(id: string) {
  const result = find(sessions(), id)
  requireUser(result.domain)
  return result
}
function findReport(id: string) {
  const report = find(reports(), id)
  requireUser(report.domain)
  return report
}
function saveSession(session: Analysis) {
  return saveItem('sessions', sessions(), { ...session, updatedAt: new Date().toISOString() })
}

export async function* readSse(stream: ReadableStream<Uint8Array>): AsyncGenerator<{ id: number; type: string; payload: unknown }> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  function parse(frame: string) {
    const lines = frame.split(/\r?\n/)
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n')
    if (!data) return
    const payload = JSON.parse(data) as { id?: number; type?: string }
    const id = Number(lines.find(line => line.startsWith('id:'))?.slice(3) ?? payload.id)
    const type = lines.find(line => line.startsWith('event:'))?.slice(6).trim() ?? payload.type
    if (!Number.isSafeInteger(id) || !type) throw new Error('分析服务返回了无法识别的流式事件。')
    return { id, type, payload }
  }
  try {
    for (;;) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      for (;;) {
        const separator = /\r?\n\r?\n/.exec(buffer)
        if (!separator) break
        const event = parse(buffer.slice(0, separator.index))
        buffer = buffer.slice(separator.index + separator[0].length)
        if (event) yield event
      }
      if (done) {
        const event = parse(buffer)
        if (event) yield event
        return
      }
    }
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}

async function request(path: string, method = 'GET', body?: unknown, signal?: AbortSignal, extraHeaders?: Record<string,string>) {
  const token = getIdentity()?.token
  const headers: Record<string, string> = { ...extraHeaders }
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let response: Response
  try {
    response = await fetch('/api' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new ApiError('无法连接分析服务，请检查服务状态后重试。', 503)
  }
  if (!response.ok) {
    if (response.status === 401 && token) {
      setIdentity(null)
      window.dispatchEvent(new Event('attribution:logout'))
    }
    const payload = await response.json().catch(() => ({}))
    throw new ApiError(typeof payload.detail === 'string' ? payload.detail : response.status === 403 ? '当前角色无权访问这项数据。' : `服务请求失败（${response.status}）。`, response.status)
  }
  return response
}
const json = async <T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> => (await request(path, method, body, signal)).json()
function query(params: object) { return new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined).map(([key, value]) => [key, typeof value === 'string' ? value : JSON.stringify(value)])).toString() }

const domainPath = (path: string, domain: string) => `${path}?${query({ domain_id: toDomain(domain) })}`
type Subscription = { id: string; domain_id: string }

async function backendSession(id: string, signal?: AbortSignal) {
  const [snapshot, cases] = await Promise.all([
    json<RemoteSession>(`/sessions/${id}`, 'GET', undefined, signal),
    json<RemoteScenario[]>(`/sessions/${id}/scenarios`, 'GET', undefined, signal),
  ])
  return remoteSession(snapshot, cases)
}
async function backendReport(id: string) {
  const [report, comments, subscriptions] = await Promise.all([
    json<RemoteReport>(`/reports/${id}`),
    json<RemoteComment[]>(`/reports/${id}/comments`),
    getIdentity()?.user.role === 'manager' ? json<Subscription[]>('/subscriptions') : Promise.resolve([]),
  ])
  return remoteReport(report, comments, subscriptions.some(item => item.domain_id === report.domain_id))
}

const eventTypes: Record<string, StreamEvent['type']> = { plan: 'plan', step: 'step', code: 'code', hypothesis: 'hypothesis', conclusion: 'conclusion', complete: 'done', failed: 'error', cancelled: 'stopped' }
async function* backendStream(id: string, response: Response, signal: AbortSignal): AsyncGenerator<StreamEvent> {
  if (!response.body) throw new Error('分析服务没有返回事件流。')
  const job = response.headers.get('X-Analysis-Job-Id') ?? undefined
  let state = await backendSession(id, signal)
  state = { ...state, status: 'running', step: 0, eventId: 0, hypotheses: [], jobId: job ?? state.jobId }
  for await (const event of readSse(response.body)) {
    const type = eventTypes[event.type]
    if (!type) continue
    if (type === 'plan') {
      const { spec } = event.payload as { spec?: RemoteSpec }
      if (spec) state = { ...state, period: { start: spec.start, end: spec.end }, baseline: spec.baseline, dimension: spec.dimensions[0] === 'day' ? 'date' : spec.dimensions[0], slices: remoteSlices(spec) }
    } else if (type === 'step') {
      const progress = event.payload as { index: number; status: string }
      state = { ...state, step: progress.index + (progress.status === 'complete' ? 1 : 0) }
    } else if (type === 'hypothesis' || type === 'code') {
      const raw = event.payload as Parameters<typeof remoteHypothesis>[0]
      const hypotheses = [...state.hypotheses]
      const index = hypotheses.findIndex(item => item.id === raw.hypothesis_id)
      if (index === -1) hypotheses.push(remoteHypothesis(raw))
      else hypotheses[index] = remoteHypothesis(raw, hypotheses[index])
      state = { ...state, hypotheses }
    } else if (type === 'conclusion') {
      state = withResult(state, event.payload as RemoteResult)
    } else {
      const payload = event.payload as { message?: string }
      state = await backendSession(id, signal)
      if (type === 'error') state.error = payload.message ?? '分析任务失败。'
    }
    state = { ...state, eventId: event.id }
    yield { id: event.id, type, analysis: state }
  }
}

async function* demoStream(id: string, after: number, signal: AbortSignal): AsyncGenerator<StreamEvent> {
  let session = findSession(id)
  if (session.eventId > after) yield { id: session.eventId, type: session.status === 'running' ? 'step' : session.status === 'stopped' ? 'stopped' : 'done', analysis: session }
  while (session.status === 'running' && !signal.aborted) {
    await new Promise(resolve => setTimeout(resolve, 260))
    if (signal.aborted) return
    session = findSession(id)
    if (session.status !== 'running') return
    const step = session.step + 1
    const type = (['plan', 'step', 'step', 'hypothesis', 'code', 'conclusion', 'step', 'done'] as const)[step]
    const finished = step === steps.length
    const evidence = step === 3 ? analysisEvidence(session, calendar(), true) : step === 5 ? analysisEvidence(session, calendar()) : {}
    session = saveSession({
      ...session, ...evidence, step, eventId: session.eventId + 1, status: finished ? 'completed' : 'running',
      messages: finished ? [...session.messages, { id: newId(), role: 'assistant', text: session.slices.length
        ? `已按「${session.slices.map(slice => slice.value).join(' / ')}」更新下钻证据。可在右栏查看贡献与检验结果。`
        : `已完成${session.metric?.name ?? ''}归因，并按${dimensions[session.dimension]}更新透视表。量化驱动、事件和建议已写入看板。` }] : session.messages,
    })
    yield { id: session.eventId, type, analysis: session }
  }
}

export const client = {
  async login(username: string, password: string): Promise<Identity> {
    if (!demoMode) {
      const result = await json<{ access_token: string; user: Parameters<typeof remoteUser>[0] }>('/auth/login', 'POST', { username, password })
      return { user: remoteUser(result.user), token: result.access_token }
    }
    const user = demoUsers.find(item => item.id === username)
    if (!user || password !== 'demo123') throw new ApiError('账号或密码不正确。', 401)
    return { user }
  },
  async metrics(filter: Filter): Promise<Metric[]> {
    if (!demoMode) {
      const { domain, ...period } = filter
      const result = await json<{ metrics: RemoteMetric[] }>(`/dashboard/metrics?${query({ ...period, domain_id: toDomain(domain) })}`)
      return result.metrics.map(remoteMetric)
    }
    requireUser(filter.domain)
    return metricList(filter)
  },
  async sessions(domain: string): Promise<AnalysisSummary[]> {
    if (!demoMode) return (await json<RemoteSession[]>(domainPath('/sessions', domain))).map(remoteSummary)
    const user = requireUser(domain)
    return sessions().filter(item => domain === 'all' ? item.domain === 'all' || user.domains.includes(item.domain) : item.domain === domain)
  },
  async session(id: string): Promise<Analysis> {
    return demoMode ? findSession(id) : backendSession(id)
  },
  async create(input: NewAnalysis): Promise<Analysis> {
    if (!demoMode) {
      const result = await json<RemoteSession>('/sessions', 'POST', { metric_id: input.metricId, question: input.question, ...input.period, baseline: input.baseline, domain_id: toDomain(input.domain), auto_start: Boolean(input.question) })
      return remoteSession(result)
    }
    requireUser(input.domain, ['analyst'])
    const metric = metricList({ ...input.period, baseline: input.baseline, domain: input.domain }).find(item => item.id === input.metricId) ?? null
    return saveSession({ id: newId(), title: metric ? `${metric.name}异动归因` : '新建归因分析', metric, period: input.period, baseline: input.baseline, domain: metric?.domain ?? input.domain, status: 'idle', step: -1, eventId: 0, messageCount: 0, updatedAt: '', messages: [], hypotheses: [], conclusions: [], actions: [], events: [], slices: [], dimension: 'channel', decomposition: null, scenarios: [] })
  },
  async *message(id: string, input: { text: string; requestId: string; dimension?: Dimension; slices?: Slice[] }, signal: AbortSignal): AsyncGenerator<StreamEvent> {
    if (!demoMode) {
      const guidance = input.slices ? input.slices.length ? `。仅保留以下筛选：${input.slices.map(slice => `${dimensions[slice.dimension]}=${slice.value}`).join('；')}` : '。清除全部切片筛选。' : ''
      const response = await request(`/sessions/${id}/messages`, 'POST', { content: input.text + guidance }, signal, { 'Idempotency-Key': input.requestId })
      yield* backendStream(id, response, signal)
      return
    }
    const session = findSession(id)
    requireUser(session.domain, ['analyst'])
    if (session.status === 'running' || session.messages.some(item => item.id === input.requestId)) {
      yield* demoStream(id, 0, signal)
      return
    }
    const mentionedDates = input.text.match(/\d{4}-\d{2}-\d{2}/g) ?? []
    const [start, end] = mentionedDates
    const dateIsValid = (date: string) => Number.isFinite(Date.parse(date)) && new Date(date).toISOString().slice(0, 10) === date
    const period = start && end && start <= end && mentionedDates.every(dateIsValid) ? { start, end } : session.period
    const baseline = input.text.includes('同比') ? 'yoy' : input.text.includes('目标差') ? 'target' : input.text.includes('环比') ? 'mom' : session.baseline
    const candidates = metricList({ ...period, baseline, domain: session.domain })
    const prompt = input.text.toLowerCase()
    const named = candidates.find(item => prompt.includes(item.name.toLowerCase()) || (item.id === 'margin' && /利润率|快消|毛利/.test(prompt)) || (item.id === 'gmv' && /交易额|电商|销售额/.test(prompt)))
    const metric = candidates.find(item => item.id === session.metric?.id) ?? named ?? candidates.find(item => item.rate !== null && item.rate < -item.threshold) ?? candidates[0]
    if (!metric) throw new ApiError('请选择有数据的目标指标。', 400)
    const dimension = input.dimension ?? (Object.entries(dimensions).find(([, label]) => input.text.includes(`按${label}`))?.[0] as Dimension | undefined) ?? session.dimension
    const explicitSlices = pivotRows({ ...session, metric }, dimension, session.slices)
      .filter(row => input.text.includes(row.label)).map(row => ({ dimension, value: row.label }))
    const slices = input.slices ?? (explicitSlices.length ? [...session.slices.filter(slice => slice.dimension !== dimension), ...explicitSlices] : session.slices)
    const started = saveSession({
      ...session, metric, period, baseline, domain: metric.domain, title: `${metric.name}异动归因`, status: 'running', step: 0, error: undefined,
      eventId: session.eventId + 1, messageCount: session.messageCount + 1, dimension, slices,
      decomposition: attribution(metric), messages: [...session.messages, { id: input.requestId, role: 'user', text: input.text }],
    })
    yield { id: started.eventId, type: 'plan', analysis: started }
    yield* demoStream(id, started.eventId, signal)
  },
  async *resume(id: string, after: number, signal: AbortSignal, jobId?: string): AsyncGenerator<StreamEvent> {
    if (demoMode) { yield* demoStream(id, after, signal); return }
    const job = jobId ?? (await backendSession(id, signal)).jobId
    if (!job) throw new ApiError('没有可恢复的分析任务。', 409)
    const response = await request(`/jobs/${job}/events?${query({ after })}`, 'GET', undefined, signal)
    yield* backendStream(id, response, signal)
  },
  async *retryJob(id: string, jobId: string, signal: AbortSignal): AsyncGenerator<StreamEvent> {
    const result = await json<{ job_id: string }>(`/jobs/${jobId}/retry`, 'POST', undefined, signal)
    yield* client.resume(id, 0, signal, result.job_id)
  },
  async stop(id: string, jobId?: string): Promise<Analysis> {
    if (!demoMode) {
      const job = jobId ?? (await backendSession(id)).jobId
      if (!job) throw new ApiError('没有正在运行的任务。', 409)
      await request(`/jobs/${job}/cancel`, 'POST')
      return backendSession(id)
    }
    const session = findSession(id)
    requireUser(session.domain, ['analyst'])
    return saveSession({ ...session, status: 'stopped', eventId: session.eventId + 1 })
  },
  async decomposition(id: string): Promise<Analysis['decomposition']> {
    return demoMode ? findSession(id).decomposition : remoteDecomposition(await json<RemoteDecomposition>(`/sessions/${id}/decomposition`))
  },
  async drilldown(id: string, dimension: Dimension, slices: Slice[], unit = ''): Promise<PivotRow[]> {
    if (demoMode) return pivotRows(findSession(id), dimension, slices)
    const secondary = dimension === 'channel' ? 'category' : 'channel'
    const path = `/sessions/${id}/drilldown?dim=${toDimension(dimension)}`
    const [base, detail] = await Promise.all([json<RemoteDrill>(path), json<RemoteDrill>(`${path}&dim=${secondary}`)])
    const parents = remoteRows(base, dimension, unit)
    const children = remoteRows(detail, secondary, unit)
    return parents.map(parent => ({ ...parent, children: children.flatMap((row, index) => detail.rows[index].dimensions[toDimension(dimension)] === parent.label ? [{ ...row, label: detail.rows[index].dimensions[secondary] ?? row.label }] : []) }))
  },
  async trend(analysis: Analysis): Promise<{ date: string; value: number | null }[]> {
    if (demoMode) return (analysis.metric?.trend ?? []).map((point, index) => ({
      date: new Date(Date.parse(analysis.period.end) - ((analysis.metric!.trend.length - index - 1) * 86_400_000)).toISOString().slice(0, 10),
      value: point,
    }))
    const data = await json<RemoteDrill>(`/sessions/${analysis.id}/drilldown?dim=day`)
    return remoteRows(data, 'date', analysis.metric?.unit ?? '').map(row => ({ date: row.label, value: row.current })).sort((left, right) => left.date.localeCompare(right.date))
  },
  async snapshot(id: string): Promise<void> {
    if (!demoMode) { await request(`/sessions/${id}/snapshots`, 'POST'); return }
    const session = findSession(id)
    requireUser(session.domain, ['analyst'])
    const snapshots = read<Analysis[]>('snapshots', [])
    write('snapshots', [...snapshots, session])
  },
  async simulate(id: string, params: Record<string, number>, name: string, save = false, signal?: AbortSignal, unit = ''): Promise<Scenario> {
    if (!demoMode) {
      const changes = Object.fromEntries(Object.entries(params).map(([key, shift]) => [key, shift / 100]))
      return remoteScenario(await json<RemoteScenario>(`/sessions/${id}/whatif`, 'POST', { changes, name, save }, signal), unit)
    }
    const session = findSession(id)
    requireUser(session.domain, ['analyst'])
    const base = session.metric?.current ?? 0
    const shift = Object.entries(params).reduce((sum, [key, value]) => sum + value * (session.decomposition?.drivers.find(driver => driver.id === key)?.sensitivity ?? 0) / 100, 0)
    const estimate = rounded(base * (1 + shift))
    const spread = Math.abs(estimate - base) * .2 + base * .006
    const leading = session.decomposition?.drivers.find(driver => driver.adjustable)
    const elasticity = leading?.sensitivity ?? 0
    const fixedShift = shift - (leading ? (params[leading.id] ?? 0) * elasticity / 100 : 0)
    const curve: [number, number][] = [-20, -10, 0, 10, 20].map(value => [value, rounded(base * (1 + fixedShift + value * elasticity / 100))])
    const result = { id: newId(), name, params, estimate, low: rounded(estimate - spread), high: rounded(estimate + spread), change: rounded(estimate - base), curve }
    if (save) {
      if (session.scenarios.length >= 3) throw new ApiError('最多保存三个情景。请先移除一个情景。', 409)
      saveSession({ ...session, scenarios: [...session.scenarios, result] })
    }
    return result
  },
  async removeScenario(id: string, scenarioId: string): Promise<Analysis> {
    if (!demoMode) { await request(`/sessions/${id}/whatif/${scenarioId}`, 'DELETE'); return backendSession(id) }
    const session = findSession(id)
    requireUser(session.domain, ['analyst'])
    return saveSession({ ...session, scenarios: session.scenarios.filter(item => item.id !== scenarioId) })
  },
  async events(domain: string): Promise<BusinessEvent[]> {
    if (!demoMode) return (await json<RemoteEvent[]>(domainPath('/events', domain))).map(remoteEvent)
    requireUser(domain)
    return calendar().filter(item => domain === 'all' || item.domain === domain)
  },
  async saveEvent(event: BusinessEvent): Promise<BusinessEvent> {
    if (!demoMode) return remoteEvent(await json<RemoteEvent>(event.id ? `/events/${event.id}` : '/events', event.id ? 'PUT' : 'POST', eventBody(event)))
    requireUser(event.domain, ['admin'])
    if (!event.title.trim() || !event.start || !event.end || event.end < event.start) throw new ApiError('请填写标题，且结束日期不能早于开始日期。', 400)
    return saveItem('events', calendar(), { ...event, id: event.id || newId() })
  },
  async removeEvent(event: BusinessEvent): Promise<void> {
    if (!demoMode) { await request(`/events/${event.id}`, 'DELETE'); return }
    requireUser(event.domain, ['admin'])
    write('events', calendar().filter(item => item.id !== event.id))
  },
  async definitions(domain: string): Promise<MetricDefinition[]> {
    if (!demoMode) {
      const preferences = read<Record<string, string | null>>('metric-parent', {})
      return remoteDefinitions(await json<RemoteDefinition[]>(domainPath('/metrics', domain))).map(item => ({ ...item, parentId: item.id in preferences ? preferences[item.id] : item.parentId }))
    }
    requireUser(domain)
    return definitions().filter(item => domain === 'all' || item.domain === domain)
  },
  async saveDefinition(definition: MetricDefinition): Promise<MetricDefinition> {
    if (!demoMode) {
      const persisted = await json<RemoteDefinition>(definition.id ? `/metrics/${definition.id}` : '/metrics', definition.id ? 'PUT' : 'POST', definitionBody(definition))
      write('metric-parent', { ...read('metric-parent', {}), [persisted.metric_id]: definition.parentId })
      return { ...remoteDefinitions([persisted])[0], parentId: definition.parentId, order: definition.order }
    }
    requireUser(definition.domain, ['admin'])
    return saveItem('definitions', definitions(), { ...definition, id: definition.id || `metric_${Date.now()}` })
  },
  async removeDefinition(definition: MetricDefinition): Promise<void> {
    if (!demoMode) { await request(`/metrics/${definition.id}`, 'DELETE'); return }
    requireUser(definition.domain, ['admin'])
    if (definitions().some(item => item.parentId === definition.id || item.formula.match(/[A-Za-z_][A-Za-z_0-9]*/g)?.includes(definition.id))) throw new ApiError('有下级指标或公式引用此指标，无法删除。', 409)
    write('definitions', definitions().filter(item => item.id !== definition.id))
  },
  async reports(domain: string): Promise<Report[]> {
    if (!demoMode) return (await json<RemoteReport[]>(domainPath('/reports', domain))).map(item => remoteReport(item))
    const user = requireUser(domain)
    return reports().filter(item => (domain === 'all' || item.domain === domain) && (user.role !== 'manager' || item.status === 'published'))
  },
  async report(id: string): Promise<Report> {
    if (!demoMode) return backendReport(id)
    const report = findReport(id)
    if (requireUser(report.domain).role === 'manager' && report.status !== 'published') throw new ApiError('只有已发布的报告可供查阅。', 403)
    return report
  },
  async generateReport(id: string): Promise<Report> {
    if (!demoMode) {
      const result = await json<{ id: string }>(`/sessions/${id}/report`, 'POST')
      return backendReport(result.id)
    }
    const session = findSession(id)
    requireUser(session.domain, ['analyst'])
    if (!session.metric || session.status !== 'completed') throw new ApiError('请先完成本轮归因分析。', 409)
    const version = Math.max(0, ...reports().filter(report => report.sessionId === id).map(report => report.version)) + 1
    return saveItem('reports', reports(), { id: newId(), sessionId: id, title: `${session.metric.name}异动归因报告`, domain: session.domain, version, status: 'draft', updatedAt: new Date().toISOString(), sections: reportSections(session), comments: [] })
  },
  async publish(id: string): Promise<Report> {
    if (!demoMode) {
      await request(`/reports/${id}`, 'PATCH', { status: 'published' })
      return backendReport(id)
    }
    const report = findReport(id)
    requireUser(report.domain, ['analyst'])
    return saveItem<Report>('reports', reports(), { ...report, status: 'published', updatedAt: new Date().toISOString() })
  },
  async subscribe(id: string, subscribed: boolean): Promise<Report> {
    if (!demoMode) {
      const report = await backendReport(id)
      const domain = toDomain(report.domain)
      if (subscribed) await request('/subscriptions', 'POST', { domain_id: domain, interval_days: 7 })
      else {
        const result = await json<Subscription[]>('/subscriptions')
        const active = result.find(item => item.domain_id === domain)
        if (active) await request(`/subscriptions/${active.id}`, 'DELETE')
      }
      return backendReport(id)
    }
    const report = await client.report(id)
    requireUser(report.domain, ['manager'])
    return saveItem('reports', reports(), { ...report, subscribed })
  },
  async comment(id: string, input: Omit<Comment, 'id' | 'author' | 'createdAt'>): Promise<Report> {
    if (!demoMode) {
      const mentions = [...new Set([...input.text.matchAll(/@([A-Za-z_][A-Za-z_0-9]*)/g)].map(item => item[1]))]
      await request(`/reports/${id}/comments`, 'POST', { section: input.section, content: input.text, quotation: input.quote ?? '', mentions })
      return backendReport(id)
    }
    const report = findReport(id)
    const user = requireUser(report.domain, ['analyst'])
    return saveItem('reports', reports(), { ...report, comments: [...report.comments, { ...input, id: newId(), author: user.name, createdAt: new Date().toISOString() }] })
  },
  async exportReport(report: Report, format: Format, sectionIds: string[]): Promise<void> {
    const { download, exportLocal } = await import('./export')
    if (demoMode) { await exportLocal(report, format, sectionIds); return }
    const params = new URLSearchParams({ fmt: format })
    for (const section of sectionIds) params.append('section', section)
    const response = await request(`/reports/${report.id}/export?${params}`)
    download(await response.blob(), `${report.title}-v${report.version}.${format}`)
  },
  demoPeriod,
}
