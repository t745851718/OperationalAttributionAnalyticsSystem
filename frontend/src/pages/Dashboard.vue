<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, CalendarDays, ChartNoAxesCombined, CircleAlert, Clock3, List, Percent, ShoppingBag, Sparkles, Wallet } from 'lucide-vue-next'
import { client, dataPeriod, demoMode, ApiError } from '../client'
import { canAnalyze, domain, errorText, theme } from '../context'
import { baselineLabels, domainLabel, number, type AnalysisSummary, type Baseline, type Metric } from '../model'
import Chart from '../components/Chart.vue'
import State from '../components/State.vue'

const route = useRoute()
const router = useRouter()
const dates = ref<[string, string]>([dataPeriod.start, dataPeriod.end])
const baseline = ref<Baseline>('mom')
const metrics = ref<Metric[]>([])
const recent = ref<AnalysisSummary[]>([])
const historyError = ref('')
const selected = ref('')
const loading = ref(true)
const error = ref<unknown>()
const createError = ref('')
const creating = ref('')
const table = ref(false)
const definition = ref<Metric>()
const icons = { gmv: ShoppingBag, conversion: Percent, net_margin: Activity, margin: Activity, revenue: Wallet }
const palette = { gmv: '#6154ea', conversion: '#137b8f', margin: '#db5670', net_margin: '#db5670', revenue: '#228263' }
const color = (metric: Metric) => palette[metric.id as keyof typeof palette] ?? '#6154ea'
const active = computed(() => metrics.value.find(item => item.id === selected.value) ?? metrics.value[0])
const anomalies = computed(() => metrics.value.filter(item => item.anomaly ?? (item.rate ?? 0) <= -item.threshold).sort((left, right) => Math.abs(right.rate ?? 0) - Math.abs(left.rate ?? 0)))
const period = computed(() => ({ start: dates.value?.[0] ?? dataPeriod.start, end: dates.value?.[1] ?? dataPeriod.end }))
const trendDates = computed(() => {
  if (active.value?.dates?.length) return active.value.dates.map(date => date.slice(5).replace('-', '/'))
  const count = active.value?.trend.length ?? 0
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(period.value.end + 'T00:00:00Z')
    date.setUTCDate(date.getUTCDate() - (count - index - 1))
    return date.toISOString().slice(5, 10).replace('-', '/')
  })
})
const additiveBenchmark = computed(() => !demoMode && ['元', '人', '单', '件'].includes(active.value?.unit ?? ''))
const benchmarkName = computed(() => `${baselineLabels[baseline.value]}${additiveBenchmark.value ? '基期日均' : '基准'}`)
const benchmark = computed(() => {
  if (!active.value || active.value.available === false) return null
  const days = Math.max(1, Math.round((Date.parse(period.value.end) - Date.parse(period.value.start)) / 86_400_000) + 1)
  return active.value.previous / (additiveBenchmark.value ? days : 1)
})
let loadingVersion = 0
async function load() {
  const version = ++loadingVersion
  loading.value = true
  error.value = undefined
  try {
    const allMetrics = await client.metrics({ ...period.value, domain: domain.value, baseline: baseline.value })
    if (version !== loadingVersion) return
    const core = new Set(['gmv', 'conversion', 'net_margin', 'revenue', route.query.metric])
    const newMetrics = demoMode ? allMetrics : allMetrics.filter(item => core.has(item.id))
    metrics.value = newMetrics.length ? newMetrics : allMetrics
    if (typeof route.query.metric === 'string' && newMetrics.some(item => item.id === route.query.metric)) selected.value = route.query.metric
    if (!metrics.value.some(item => item.id === selected.value)) selected.value = metrics.value[0]?.id ?? ''
  } catch (failure) { if (version === loadingVersion) error.value = failure }
  finally { if (version === loadingVersion) loading.value = false }
}
watch([period, domain, baseline, () => route.query.metric], load, { immediate: true })
async function loadHistory() {
  const scope = domain.value
  historyError.value = ''
  try {
    const records = await client.sessions(scope)
    if (domain.value === scope) recent.value = records.slice(0, 5)
  } catch (failure) {
    if (domain.value === scope) { recent.value = []; historyError.value = errorText(failure) }
  }
}
watch(domain, loadHistory, { immediate: true })
watch(() => route.query.metric, id => { if (typeof id === 'string' && metrics.value.some(item => item.id === id)) selected.value = id })
async function start(metric: Metric) {
  creating.value = metric.id
  createError.value = ''
  try {
    const session = await client.create({ metricId: metric.id, period: period.value, baseline: baseline.value, domain: metric.domain })
    await router.push({ name: 'workbench', params: { id: session.id }, query: { start: '1' } })
  } catch (failure) { createError.value = errorText(failure) }
  finally { creating.value = '' }
}
function spark(metric: Metric) {
  const ink = (metric.rate ?? 0) < 0 ? '#db6278' : '#29a17a'
  return { grid: { left: 0, right: 2, top: 4, bottom: 4 }, xAxis: { type: 'category', show: false, boundaryGap: false }, yAxis: { type: 'value', show: false, scale: true }, series: [{ type: 'line', data: metric.trend, showSymbol: false, smooth: .35, lineStyle: { color: ink, width: 2 }, areaStyle: { color: ink + '13' } }] }
}
const chartOptions = computed(() => {
  const metric = active.value
  if (!metric) return {}
  const ink = color(metric)
  const dark = theme.value === 'dark'
  return {
    grid: { left: 60, right: 22, top: 24, bottom: 36 },
    tooltip: { trigger: 'axis', valueFormatter: (value: number) => number(value, metric.unit) },
    xAxis: { type: 'category', boundaryGap: false, data: trendDates.value, axisTick: { show: false }, axisLine: { lineStyle: { color: dark ? '#343d58' : '#e6e8f2' } }, axisLabel: { color: dark ? '#c3c9dc' : '#667088', margin: 15 } },
    yAxis: { type: 'value', scale: true, splitNumber: 4, axisLabel: { color: dark ? '#c3c9dc' : '#667088', formatter: (value: number) => metric.unit === '元' ? `${Number((value / 10000).toFixed(1))}万` : `${value}%` }, splitLine: { lineStyle: { type: 'dashed', color: dark ? '#333d56' : '#e7eaf3' } } },
    series: [
      { name: '观察序列', type: 'line', data: metric.trend, showSymbol: false, smooth: .3, lineStyle: { color: ink, width: 3 }, itemStyle: { color: ink }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: ink + '42' }, { offset: 1, color: ink + '02' }] } } },
      { name: benchmarkName.value, type: 'line', data: metric.trend.map(() => benchmark.value), showSymbol: false, lineStyle: { color: '#9ca6c1', type: 'dashed', width: 1.5 }, itemStyle: { color: '#9ca6c1' } },
    ],
  }
})
</script>

<template>
  <div class="page dashboard-page">
    <div class="page-heading dashboard-heading">
      <div><h1>指标异动大盘</h1><p>监控核心经营指标，发现变化并发起归因分析。</p></div>
      <el-button v-if="canAnalyze" class="primary-cta" type="primary" @click="router.push({ name: 'workbench', query: { new: '1' } })"><Sparkles :size="17" /> 新建归因分析</el-button>
    </div>
    <div class="filter-bar">
      <div class="filter-brand"><span class="filter-ico"><CalendarDays :size="16" /></span><strong>监控周期</strong></div>
      <el-date-picker v-model="dates" type="daterange" value-format="YYYY-MM-DD" format="YYYY-MM-DD" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" :clearable="false" aria-label="指标监控日期" />
      <span class="filter-separator"></span>
      <div class="segments" aria-label="对比基期"><button v-for="(name, key) in baselineLabels" :key="key" type="button" :aria-pressed="baseline === key" @click="baseline = key">{{ name }}</button></div>
      <span v-if="!loading && !error" class="filter-count">监控 <strong>{{ metrics.length }}</strong> 项指标 · <strong class="danger">{{ anomalies.length }}</strong> 项异常</span>
    </div>
    <State v-if="loading" mode="loading" />
    <State v-else-if="error" :mode="error instanceof ApiError && error.status === 403 ? 'forbidden' : 'error'" :detail="errorText(error)" retry @retry="load" />
    <State v-else-if="!metrics.length" mode="empty" title="该周期没有监控指标" detail="可切换业务线或调整日期。" />
    <template v-else>
      <p v-if="createError" class="form-error" role="alert">{{ createError }}</p>
      <div class="section-heading"><h2>核心指标</h2><span class="muted">{{ domainLabel(domain) }}</span></div>
      <div class="metric-grid">
        <article v-for="metric in metrics" :key="metric.id" class="metric-card panel" :class="{ 'metric-abnormal': anomalies.some(item => item.id === metric.id), 'metric-selected': active?.id === metric.id }">
          <div class="metric-top"><span class="metric-icon" :style="{ '--metric-color': color(metric) }"><component :is="icons[metric.id as keyof typeof icons] ?? Activity" :size="19" /></span><span v-if="metric.available === false" class="tag neutral">数据不足</span><span v-else-if="anomalies.some(item => item.id === metric.id)" class="tag rose"><span class="status-dot"></span>异常</span><span v-else class="tag green"><span class="status-dot"></span>正常</span></div>
          <button class="metric-name" :aria-pressed="active?.id === metric.id" @click="selected = metric.id">{{ metric.name }}</button>
          <button class="metric-number metric-value" :aria-label="`查看${metric.name}口径`" @click="definition = metric">{{ number(metric.available === false ? null : metric.current, metric.unit) }}</button>
          <div class="metric-changes"><strong :class="(metric.rate ?? 0) < 0 ? 'danger' : 'positive'"><ArrowDownRight v-if="(metric.rate ?? 0) < 0" :size="15" /><ArrowUpRight v-else :size="15" />{{ number(metric.rate, '%', true) }}</strong><span>{{ baselineLabels[baseline] }}</span></div>
          <Chart :option="spark(metric)" :label="`${metric.name}趋势`" :height="40" />
          <div class="metric-foot"><span :title="metric.description">阈值 {{ demoMode ? '−' : '±' }}{{ metric.threshold }}%</span><button v-if="canAnalyze && anomalies.some(item => item.id === metric.id)" class="link-btn" :disabled="!!creating" @click="start(metric)">{{ creating === metric.id ? '创建中…' : '智能归因分析' }}<ArrowRight :size="13" /></button><button v-else class="link-btn" @click="definition = metric">查看口径<ArrowRight :size="13" /></button></div>
        </article>
      </div>
      <div class="dashboard-grid">
        <section class="panel trend-panel">
          <div class="panel-heading"><div><h2><ChartNoAxesCombined :size="18" />指标趋势</h2><p>{{ active?.description }} <span v-if="active">· {{ baselineLabels[baseline] }}对比</span></p></div><button class="icon-btn" :aria-label="table ? '显示趋势图' : '查看数据表'" :aria-pressed="table" @click="table = !table"><List :size="18" /></button></div>
          <div class="chart-toolbar"><div class="chip-row" aria-label="趋势指标"><button v-for="metric in metrics" :key="metric.id" class="chip" :aria-pressed="active?.id === metric.id" @click="selected = metric.id">{{ metric.name }}</button></div><span class="legend"><i></i>观察序列 <i class="dashed"></i>{{ benchmarkName }}</span></div>
          <div v-if="table && active" class="trend-table table-scroll">
            <p>统计口径：{{ active.description }} · 对比基期 {{ number(active.available === false ? null : active.previous, active.unit) }}</p>
            <table class="data-table"><thead><tr><th>日期</th><th>观察值</th><th>{{ benchmarkName }}</th></tr></thead><tbody><tr v-for="(point, index) in active.trend" :key="index"><td>{{ trendDates[index] }}</td><td>{{ number(point, active.unit) }}</td><td>{{ number(benchmark, active.unit) }}</td></tr></tbody></table>
          </div>
          <Chart v-else :option="chartOptions" :label="`${active?.name ?? '指标'}观察序列与基期趋势`" :height="264" />
        </section>
        <section class="panel attention-panel">
          <div class="panel-heading"><div><h2><CircleAlert :size="18" />待关注</h2><p>按偏离程度排序</p></div><span class="tag rose">{{ anomalies.length }} 项异常</span></div>
          <div v-if="anomalies.length" class="attention-list">
            <article v-for="(metric, index) in anomalies" :key="metric.id" class="attention-item">
              <span class="attention-rank">{{ String(index + 1).padStart(2, '0') }}</span><div><strong>{{ metric.name }}</strong><small>{{ domainLabel(metric.domain) }} · 触发异动阈值</small></div><strong class="danger">{{ number(metric.rate, '%', true) }}</strong>
            </article>
          </div>
          <State v-else mode="empty" title="未触发异常阈值" />
          <div class="attention-footer"><Clock3 :size="15" />监控截至 {{ period.end }}</div>
        </section>
      </div>
      <section class="panel recent-panel">
        <div class="panel-heading"><div><h2><Clock3 :size="18" />最近归因会话</h2><p>继续查看分析进度与证据。</p></div><RouterLink class="link-btn" :to="{ name: 'workbench' }">打开工作台 <ArrowRight :size="14" /></RouterLink></div>
        <div v-if="recent.length" class="recent-list"><RouterLink v-for="item in recent" :key="item.id" :to="{ name: 'workbench', params: { id: item.id } }"><span>{{ item.title }}<small>{{ domainLabel(item.domain) }}</small></span><span class="tag" :class="item.status === 'completed' ? 'green' : 'lavender'">{{ { idle: '待开始', running: '分析中', completed: '已完成', stopped: '已停止', failed: '失败' }[item.status] }}</span></RouterLink></div>
        <div v-else-if="historyError" class="recent-empty" role="status">{{ historyError }} <button class="link-btn" @click="loadHistory">重试会话列表</button></div>
        <p v-else class="recent-empty">暂无归因会话。{{ canAnalyze ? '可从异常指标发起分析。' : '' }}</p>
      </section>
    </template>
    <el-dialog :model-value="!!definition" :title="`${definition?.name ?? ''}指标口径`" width="min(490px, 92vw)" @update:model-value="definition = undefined">
      <p>{{ definition?.description }}</p>
      <dl v-if="definition" class="definition-values"><div><dt>观测值</dt><dd>{{ number(definition.available === false ? null : definition.current, definition.unit) }}</dd></div><div><dt>{{ baselineLabels[baseline] }}基期值</dt><dd>{{ number(definition.available === false ? null : definition.previous, definition.unit) }}</dd></div><div><dt>变动率</dt><dd>{{ number(definition.rate, '%', true) }}</dd></div><div><dt>异动阈值</dt><dd>{{ demoMode ? '−' : '±' }}{{ definition.threshold }}%</dd></div></dl>
    </el-dialog>
  </div>
</template>
