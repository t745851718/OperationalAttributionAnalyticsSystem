<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Activity, ArrowUp, BookOpen, Check, ChevronLeft, ChevronRight, CircleStop, Code2, GripVertical, History, Plus, Sparkles } from 'lucide-vue-next'
import { client, dataPeriod, demoMode, ApiError } from '../client'
import { canAnalyze, domain, errorText } from '../context'
import { baselineLabels, dimensions, domainLabel, newId, number, steps, type Analysis, type AnalysisSummary, type Dimension, type Hypothesis, type Slice } from '../model'
import AttributionBoard from '../components/AttributionBoard.vue'
import State from '../components/State.vue'

const route = useRoute()
const router = useRouter()
const session = ref<Analysis | null>(null)
const history = ref<AnalysisSummary[]>([])
const historyError = ref('')
const loading = ref(false)
const pageError = ref<unknown>()
const error = ref('')
const input = ref('')
const sending = ref(false)
const reporting = ref(false)
const resumed = ref(false)
const fullscreen = ref(false)
const collapsed = ref(localStorage.getItem('attribution.workbench.collapsed') === '1')
const width = ref(Math.max(420, Math.min(670, Number(localStorage.getItem('attribution.workbench.width')) || 454)))
const conversation = ref<HTMLElement>()
const composer = ref<HTMLTextAreaElement>()
let current: AbortController | undefined
let routeGeneration = 0
let historyGeneration = 0
let initialText: string | undefined
let lastRequest: { text: string; requestId: string; dimension?: Dimension; slices?: Slice[] } | undefined
const metric = computed(() => session.value?.metric)
const deltaUnit = computed(() => metric.value?.unit === '%' ? ' pp' : metric.value?.unit)
const working = computed(() => sending.value || session.value?.status === 'running')
const statusLabels = { idle: '待开始', running: '分析中', completed: '已完成', stopped: '已停止', failed: '失败' }
const hypLabels: Record<Hypothesis['status'], string> = { pending: '验证中', confirmed: '成立', excluded: '已排除', insufficient: '样本不足', timeout: '已终止', failed: '验证失败' }
const hypColors: Record<Hypothesis['status'], string> = { pending: 'lavender', confirmed: 'green', excluded: 'neutral', insufficient: 'amber', timeout: 'rose', failed: 'rose' }
const prompts = computed(() => metric.value?.domain === 'fmcg' ? ['按渠道下钻', '复核连锁商超的佣金影响', '按品类分析原料成本'] : ['按渠道下钻', '排除大促影响', '为什么转化率下降？'])
const blankPrompts = ['分析 GMV 下滑的原因', '分析快消品净利率下降']

watch(collapsed, value => localStorage.setItem('attribution.workbench.collapsed', value ? '1' : '0'))
watch(width, value => localStorage.setItem('attribution.workbench.width', String(value)))
watch(domain, updateHistory, { immediate: true })
watch(() => route.params.id, loadSession, { immediate: true })
watch(() => session.value?.messages.filter(message => message.role === 'user').length, async () => {
  await nextTick()
  const panel = conversation.value
  const messages = panel?.querySelectorAll<HTMLElement>('.message-row.user')
  const latest = messages?.item(messages.length - 1)
  if (panel && latest) panel.scrollTop += latest.getBoundingClientRect().top - panel.getBoundingClientRect().top - 10
})

async function updateHistory() {
  const generation = ++historyGeneration
  historyError.value = ''
  try {
    const items = await client.sessions(domain.value)
    if (generation === historyGeneration) history.value = items
  } catch (failure) { if (generation === historyGeneration) historyError.value = errorText(failure) }
}

async function loadSession() {
  const generation = ++routeGeneration
  current?.abort()
  sending.value = false
  session.value = null
  error.value = ''
  pageError.value = undefined
  resumed.value = false
  fullscreen.value = false
  lastRequest = undefined
  const id = route.params.id
  loading.value = typeof id === 'string' && id.length > 0
  if (!loading.value || typeof id !== 'string') return
  try {
    const snapshot = await client.session(id)
    if (generation !== routeGeneration) return
    session.value = snapshot
    loading.value = false
    if (snapshot.status === 'running') {
      resumed.value = !initialText
      initialText = undefined
      void resume()
    } else if (snapshot.status === 'idle' && (route.query.start === '1' || initialText)) {
      const text = initialText ?? `请分析 ${snapshot.metric?.name ?? snapshot.title} 的异动。`
      initialText = undefined
      if (route.query.start) void router.replace({ name: 'workbench', params: { id } })
      void send(text)
    }
  } catch (failure) { if (generation === routeGeneration) pageError.value = failure }
  finally { if (generation === routeGeneration) loading.value = false }
}

async function refresh() {
  const id = session.value?.id
  if (!id) return
  try {
    const latest = await client.session(id)
    const visible = session.value
    if (visible?.id !== id) return
    if (latest.jobId !== visible.jobId || latest.eventId >= visible.eventId) session.value = latest
    else if (!demoMode && latest.status !== 'running') session.value = { ...latest, eventId: visible.eventId }
  } catch (failure) { if (session.value?.id === id) error.value = errorText(failure) }
}

async function follow(id: string, create: (signal: AbortSignal) => AsyncGenerator<import('../model').StreamEvent>) {
  current?.abort()
  const controller = new AbortController()
  current = controller
  sending.value = true
  error.value = ''
  try {
    for await (const event of create(controller.signal)) {
      if (controller.signal.aborted || session.value?.id !== id) return
      if (event.analysis.jobId === session.value.jobId && event.id <= session.value.eventId) continue
      session.value = { ...event.analysis, eventId: event.id }
    }
    if (!controller.signal.aborted && session.value?.id === id && session.value.status === 'running') error.value = '事件流已断开，可以恢复分析。'
  } catch (failure) {
    if (!controller.signal.aborted && session.value?.id === id) error.value = errorText(failure)
  } finally {
    if (current === controller && !controller.signal.aborted) {
      sending.value = false
      void updateHistory()
    }
  }
}
function resume() {
  const id = session.value?.id
  const after = session.value?.eventId ?? 0
  const job = session.value?.jobId
  if (id) return follow(id, signal => client.resume(id, after, signal, job))
}
async function send(text = input.value, dimension?: Dimension, slices?: Slice[]) {
  text = text.trim()
  if (!text || (working.value && !error.value) || !canAnalyze.value) return
  input.value = ''
  if (!session.value) {
    sending.value = true
    error.value = ''
    try {
      const created = await client.create({ question: text, period: dataPeriod, baseline: 'mom', domain: domain.value })
      initialText = text
      await router.push({ name: 'workbench', params: { id: created.id } })
      void updateHistory()
    } catch (failure) {
      error.value = errorText(failure)
      input.value = text
    } finally { if (!session.value) sending.value = false }
    return
  }
  const id = session.value.id
  const payload = { text, requestId: newId(), dimension, slices }
  lastRequest = payload
  await follow(id, signal => client.message(id, payload, signal))
}
function retry() {
  if (session.value?.status === 'running') { void resume(); return }
  const id = session.value?.id
  const job = session.value?.jobId
  if (!demoMode && id && job && session.value?.status === 'failed') { void follow(id, signal => client.retryJob(id, job, signal)); return }
  const request = lastRequest
  if (id && request) void follow(id, signal => client.message(id, request, signal))
}
async function stop() {
  const id = session.value?.id
  if (!id) return
  try {
    const stopped = await client.stop(id, session.value?.jobId)
    if (session.value?.id !== id) return
    current?.abort()
    session.value = stopped
    sending.value = false
    error.value = ''
    void updateHistory()
  } catch (failure) { error.value = errorText(failure) }
}
function newAnalysis() {
  input.value = ''
  void router.push({ name: 'workbench', query: { new: '1' } }).then(() => composer.value?.focus())
}
function submitKey(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    if (!working.value) void send()
  }
}
function drill(dimension: Dimension, slices: Slice[]) {
  if (!demoMode && dimension === 'date') {
    const day = slices.find(slice => slice.dimension === 'date')?.value
    if (day) void send(`按日期下钻，仅分析 ${day} 当日，保留原有的其他切片。`)
    return
  }
  void send(`按${dimensions[dimension]}下钻：${slices.map(slice => `${dimensions[slice.dimension]}=${slice.value}`).join(' > ')}`, dimension, slices)
}
function popSlice(index: number) {
  const slices = session.value?.slices.slice(0, index) ?? []
  const dimension = slices.at(-1)?.dimension ?? 'channel'
  void send(slices.length ? `返回 ${slices.at(-1)?.value} 切片` : '返回整体视图', dimension, slices)
}
async function generateReport(openExport = false) {
  if (!session.value || reporting.value) return
  reporting.value = true
  try {
    const report = await client.generateReport(session.value.id)
    await router.push({ name: 'reports', params: { id: report.id }, query: openExport ? { export: 'pdf' } : {} })
  } catch (failure) { error.value = errorText(failure) }
  finally { reporting.value = false }
}
function resizeStart(event: PointerEvent) {
  const grip = event.currentTarget as HTMLElement
  const initial = event.clientX
  const starting = width.value
  grip.setPointerCapture(event.pointerId)
  const move = (next: PointerEvent) => { width.value = Math.min(670, Math.max(420, starting + initial - next.clientX)) }
  grip.addEventListener('pointermove', move)
  grip.addEventListener('lostpointercapture', () => grip.removeEventListener('pointermove', move), { once: true })
}
function resizeKey(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  width.value = Math.min(670, Math.max(420, width.value + (event.key === 'ArrowLeft' ? 16 : -16)))
}
onBeforeUnmount(() => { current?.abort(); routeGeneration++; historyGeneration++ })
</script>

<template>
  <div class="page workbench-page" @keydown.esc="fullscreen = false">
    <div class="page-heading workbench-heading"><div><h1>归因分析工作台</h1><p>围绕指标异动追问、下钻，并验证量化证据。</p></div><span v-if="session" class="tag" :class="session.status === 'completed' ? 'green' : 'lavender'"><span class="status-dot"></span>{{ statusLabels[session.status] }}</span></div>
    <div class="workbench-grid panel" :class="{ 'history-collapsed': collapsed }" :style="{ '--board-width': width + 'px' }">
      <aside class="session-pane" aria-label="会话历史">
        <div class="session-pane-heading"><h2 v-if="!collapsed"><History :size="17" /> 会话</h2><button class="icon-btn" :aria-label="collapsed ? '展开会话导航' : '折叠会话导航'" :aria-expanded="!collapsed" @click="collapsed = !collapsed"><ChevronRight v-if="collapsed" :size="16" /><ChevronLeft v-else :size="16" /></button></div>
        <template v-if="!collapsed">
          <el-button v-if="canAnalyze" class="new-session" type="primary" plain @click="newAnalysis"><Plus :size="16" /> 新建分析</el-button>
          <p v-if="historyError" class="form-error">{{ historyError }} <button class="link-btn" @click="updateHistory">重试</button></p>
          <div class="session-list">
            <RouterLink v-for="item in history" :key="item.id" :to="{ name: 'workbench', params: { id: item.id } }" :class="{ current: item.id === session?.id }"><span class="session-status" :class="item.status"></span><div><strong>{{ item.title }}</strong><small>{{ domainLabel(item.domain) }}</small></div></RouterLink>
            <p v-if="!history.length && !historyError" class="muted">暂无归因会话</p>
          </div>
          <div v-if="metric" class="session-metric"><span>目标指标</span><h3>{{ metric.name }}</h3><strong>{{ number(metric.current, metric.unit) }}</strong><dl><div><dt>基期值</dt><dd>{{ number(metric.previous, metric.unit) }}</dd></div><div><dt>差异额</dt><dd :class="metric.delta < 0 ? 'danger' : 'positive'">{{ number(metric.delta, deltaUnit, true) }}</dd></div><div><dt>差异率</dt><dd :class="(metric.rate ?? 0) < 0 ? 'danger' : 'positive'">{{ number(metric.rate, '%', true) }}</dd></div></dl><small>{{ baselineLabels[session!.baseline] }} · {{ session!.period.start }} 至 {{ session!.period.end }}</small></div>
        </template>
        <button v-else-if="canAnalyze" class="icon-btn" aria-label="新建分析" @click="newAnalysis"><Plus :size="18" /></button>
      </aside>
      <section class="conversation-pane" aria-label="对话探索">
        <header class="workbench-panel-heading"><div><span class="mini-icon lavender"><Sparkles :size="17" /></span><div><h2>{{ session?.title ?? '对话探索' }}</h2><small>{{ metric ? `${domainLabel(metric.domain)} · ${baselineLabels[session!.baseline]}` : '自然语言归因分析' }}</small></div></div><button v-if="session?.status === 'running'" class="stop-btn" @click="stop"><CircleStop :size="15" />停止分析</button></header>
        <div v-if="session?.slices.length" class="slice-breadcrumb" aria-label="下钻切片"><button class="link-btn" :disabled="working || !canAnalyze" @click="popSlice(0)">整体</button><template v-for="(slice, index) in session.slices" :key="slice.dimension"><ChevronRight :size="13" /><button class="chip" :disabled="working || !canAnalyze" @click="popSlice(index + 1)">{{ dimensions[slice.dimension] }}={{ slice.value }}</button></template></div>
        <div ref="conversation" class="conversation-scroll">
          <State v-if="loading" mode="loading" />
          <State v-else-if="pageError" :mode="pageError instanceof ApiError && pageError.status === 403 ? 'forbidden' : 'error'" :detail="errorText(pageError)" retry @retry="loadSession" />
          <State v-else-if="!session?.messages.length && !canAnalyze" mode="empty" title="选择一条归因会话" detail="业务负责人可在此查看分析步骤与证据。" />
          <div v-else-if="!session?.messages.length" class="conversation-empty"><span class="welcome-mark"><Sparkles :size="26" /></span><h3>想分析哪个经营指标？</h3><p>描述指标异动，或选用下方问题发起归因。</p><div class="starter-prompts"><button v-for="prompt in blankPrompts" :key="prompt" :disabled="sending" @click="send(prompt)">{{ prompt }} <ChevronRight :size="14" /></button></div></div>
          <template v-else>
            <div v-if="resumed" class="inline-note" role="status"><Check :size="14" />已恢复分析任务</div>
            <article v-for="message in session.messages" :key="message.id" class="message-row" :class="message.role"><span v-if="message.role === 'assistant'" class="message-icon"><Sparkles :size="14" /></span><div><small>{{ message.role === 'user' ? '你' : '归因助手' }}</small><p>{{ message.text }}</p></div></article>
            <div class="analysis-run">
              <div class="timeline-heading"><Activity :size="15" /><strong>分析路径</strong><span class="tag" :class="session.status === 'completed' ? 'green' : 'lavender'">{{ statusLabels[session.status] }}</span></div>
              <ol class="step-list" aria-label="分析步骤"><li v-for="(step, index) in steps" :key="step" :class="{ done: session.step > index, active: session.step === index && session.status === 'running' }" :aria-current="session.step === index && session.status === 'running' ? 'step' : undefined"><span><Check v-if="session.step > index" :size="11" /><template v-else>{{ index + 1 }}</template></span>{{ step }}</li></ol>
              <div v-if="session.status === 'running'" class="running-line" role="status"><span class="pulse-dot"></span>{{ session.step === 4 ? '正在执行 SQL 与统计检验…' : session.step === 1 ? '正在拆解指标贡献…' : `正在${steps[session.step] ?? '分析'}…` }}</div>
              <p v-if="session.status === 'stopped'" class="inline-note" role="status">分析已停止，部分结果可能尚未生成。</p>
              <p v-if="session.status === 'failed'" class="form-error" role="alert">{{ session.error ?? '分析任务失败。' }} <button v-if="canAnalyze && !demoMode" class="link-btn" @click="retry">重试分析</button></p>
            </div>
            <section v-if="session.hypotheses.length" class="hypothesis-list" aria-label="归因候选假设">
              <div class="timeline-heading"><BookOpen :size="15" /><strong>候选假设</strong><small>{{ session.hypotheses.length }} 条</small></div>
              <article v-for="hyp in session.hypotheses" :key="hyp.id" class="hypothesis-card">
                <div><span class="tag" :class="hypColors[hyp.status]">{{ hypLabels[hyp.status] }}</span><small>{{ hyp.driver }}</small></div><h4>{{ hyp.statement }}</h4>
                <div class="hyp-stats"><div><span>置信度</span><strong>{{ number(hyp.confidence == null ? null : hyp.confidence * 100, '%') }}</strong><progress v-if="hyp.confidence != null" max="1" :value="hyp.confidence" :aria-label="`${hyp.statement}置信度`"></progress></div><div><span>p 值</span><strong>{{ hyp.p == null ? '—' : Number(hyp.p.toPrecision(4)) }}</strong></div><div><span>效应量</span><strong>{{ number(hyp.effect) }}</strong></div></div>
                <details><summary><Code2 :size="14" /> 查看沙箱代码与执行结果</summary><pre class="code-block"><code>{{ hyp.code }}</code></pre><p>{{ hyp.output || '等待执行结果。' }}</p><small v-if="hyp.elapsed != null">耗时 {{ hyp.elapsed }} ms</small></details>
              </article>
            </section>
          </template>
        </div>
        <footer v-if="canAnalyze && !pageError" class="composer">
          <p v-if="error" class="form-error" role="alert">{{ error }} <button v-if="session" class="link-btn" @click="retry">重试 / 恢复</button></p>
          <div v-if="session?.messages.length" class="chip-row followups"><button v-for="prompt in prompts" :key="prompt" class="chip" :disabled="working" @click="send(prompt)">{{ prompt }}</button></div>
          <form @submit.prevent="send()"><textarea ref="composer" v-model="input" aria-label="输入归因问题" placeholder="输入问题，例如：按渠道下钻 GMV 下滑的原因" rows="2" @keydown="submitKey"></textarea><el-button native-type="submit" type="primary" :disabled="!input.trim() || working" aria-label="发送问题"><ArrowUp :size="18" /></el-button></form>
          <small>Enter 发送 · Shift + Enter 换行</small>
        </footer>
      </section>
      <div class="board-grip" role="separator" tabindex="0" aria-label="调整看板宽度" aria-orientation="vertical" :aria-valuenow="width" :aria-valuemin="420" :aria-valuemax="670" @pointerdown="resizeStart" @keydown="resizeKey"><GripVertical :size="13" /></div>
      <AttributionBoard :analysis="session" :fullscreen="fullscreen" :refreshing="working && (session?.messageCount ?? 0) > 1" @fullscreen="fullscreen = !fullscreen" @drill="drill" @refresh="refresh" @report="generateReport" />
    </div>
  </div>
</template>
