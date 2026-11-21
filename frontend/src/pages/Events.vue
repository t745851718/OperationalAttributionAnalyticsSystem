<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, CalendarDays, Clock3, List, MapPin, Plus } from 'lucide-vue-next'
import { ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { ApiError, client, dataPeriod, demoMode } from '../client'
import { canManage, domain, errorText, theme } from '../context'
import { domainLabel, domains, number, type BusinessEvent, type EventKind, type Metric } from '../model'
import Chart from '../components/Chart.vue'
import State from '../components/State.vue'

const route = useRoute()
const kinds: EventKind[] = ['大促', '故障', '政策', '竞品', '宏观', '运营']
const filters = ref<EventKind[]>([])
const view = ref<'timeline' | 'month'>('timeline')
const months = ref(dataPeriod.end.slice(0, 7))
const events = ref<BusinessEvent[]>([])
const metrics = ref<Metric[]>([])
const metricId = ref('')
const selected = ref<BusinessEvent>()
const editing = ref(false)
const drawer = ref(false)
const draft = ref<BusinessEvent>(emptyEvent())
const scopeText = ref('')
const failed = ref<unknown>()
const formError = ref('')
const loading = ref(true)
const pending = ref(false)
const showTable = ref(false)
const dates = computed(() => {
  const [year, month] = months.value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, 1))
  const offset = (date.getUTCDay() + 6) % 7
  const length = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return Array.from({ length: Math.ceil((offset + length) / 7) * 7 }, (_, index) => {
    const day = new Date(Date.UTC(year, month - 1, index - offset + 1))
    return { date: day.toISOString().slice(0, 10), display: day.getUTCDate(), dim: day.getUTCMonth() !== month - 1 }
  })
})
const filtered = computed(() => events.value.filter(item => !filters.value.length || filters.value.includes(item.type)).sort((a, b) => b.start.localeCompare(a.start)))
const metric = computed(() => metrics.value.find(item => item.id === metricId.value))
const trendDates = computed(() => metric.value?.dates ?? metric.value?.trend.map((_, index, array) => new Date(Date.parse(dataPeriod.end) - (array.length - index - 1) * 86400000).toISOString().slice(0, 10)) ?? [])
const chart = computed(() => {
  const relevant = filtered.value.filter(event => event.domain === metric.value?.domain && event.end >= (trendDates.value[0] ?? '') && event.start <= (trendDates.value.at(-1) ?? ''))
  return {
    grid: { left: 76, right: 16, top: 24, bottom: 29 },
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: trendDates.value, axisLabel: { formatter: (value: string) => value.slice(5), color: theme.value === 'dark' ? '#c6ccdf' : '#667088' } },
    yAxis: { type: 'value', scale: true, splitNumber: 4, axisLabel: { formatter: (value: number) => metric.value?.unit === '元' ? `${value / 10000}万` : number(value, metric.value?.unit) } },
    series: [{ type: 'line', data: metric.value?.trend, smooth: true, lineStyle: { color: '#6554e9', width: 3 }, itemStyle: { color: '#6554e9' }, markArea: { data: relevant.map(event => [{ xAxis: event.start < trendDates.value[0] ? trendDates.value[0] : event.start, name: event.title, itemStyle: { color: '#9b87ed3b' }, label: { show: false } }, { xAxis: event.end > trendDates.value.at(-1)! ? trendDates.value.at(-1) : event.end }]) } }],
  }
})
let version = 0
function emptyEvent(): BusinessEvent {
  return { id: '', title: '', type: '大促', domain: domain.value === 'all' ? 'commerce' : domain.value, start: dataPeriod.end, end: dataPeriod.end, scope: [], note: '' }
}
async function load() {
  const active = ++version
  failed.value = undefined
  loading.value = true
  try {
    const [calendar, values] = await Promise.all([client.events(domain.value), client.metrics({ ...dataPeriod, domain: domain.value, baseline: 'mom' })])
    if (version !== active) return
    events.value = calendar
    metrics.value = values
    if (metricId.value && !metric.value) metricId.value = ''
    const linked = events.value.find(item => item.id === route.query.event)
    if (linked) open(linked, false)
  } catch (failure) { if (version === active) failed.value = failure }
  finally { if (version === active) loading.value = false }
}
watch([domain, () => route.query.event], load, { immediate: true })
function shiftMonth(delta: number) {
  const [year, month] = months.value.split('-').map(Number)
  months.value = new Date(Date.UTC(year, month - 1 + delta, 1)).toISOString().slice(0, 7)
}
function eventsOn(date: string) { return filtered.value.filter(item => item.start <= date && date <= item.end) }
function open(event?: BusinessEvent, edit = false) {
  selected.value = event
  draft.value = event ? { ...event, scope: [...event.scope] } : emptyEvent()
  scopeText.value = draft.value.scope.join('，')
  editing.value = edit
  formError.value = ''
  drawer.value = true
}
async function remove() {
  if (!selected.value || pending.value) return
  const event = selected.value
  try { await ElMessageBox.confirm(`删除「${event.title}」？`, '删除事件', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }) }
  catch { return }
  pending.value = true
  formError.value = ''
  try { await client.removeEvent(event); drawer.value = false; await load() }
  catch (failure) { formError.value = errorText(failure) }
  finally { pending.value = false }
}
async function save() {
  if (!draft.value.title.trim() || !draft.value.start || !draft.value.end || draft.value.end < draft.value.start) {
    formError.value = '请填写标题，结束日期须等于或晚于开始日期。'
    return
  }
  pending.value = true
  formError.value = ''
  try {
    await client.saveEvent({ ...draft.value, title: draft.value.title.trim(), scope: scopeText.value.split(/[，,]/).map(value => value.trim()).filter(Boolean) })
    drawer.value = false
    await load()
  } catch (failure) { formError.value = errorText(failure) }
  finally { pending.value = false }
}
</script>

<template>
  <div class="page">
    <div class="page-heading"><div><h1>业务事件日历</h1><p>查看影响指标的营销、运营和外部事件。</p></div><el-button v-if="canManage" type="primary" class="primary-cta" @click="open(undefined, true)"><Plus :size="17" />新建事件</el-button></div>
    <div class="filter-bar wrap"><div class="filter-brand"><span class="filter-ico"><CalendarDays :size="16" /></span><strong>事件类型</strong></div><div class="chip-row"><button v-for="kind in kinds" :key="kind" class="chip" :aria-pressed="filters.includes(kind)" @click="filters = filters.includes(kind) ? filters.filter(item => item !== kind) : [...filters, kind]">{{ kind }}</button></div><div class="segments push-right"><button :aria-pressed="view === 'timeline'" @click="view = 'timeline'"><List :size="15" />时间线</button><button :aria-pressed="view === 'month'" @click="view = 'month'"><CalendarDays :size="15" />月历</button></div></div>
    <State v-if="loading" mode="loading" />
    <State v-else-if="failed" :mode="failed instanceof ApiError && failed.status === 403 ? 'forbidden' : 'error'" :detail="errorText(failed)" retry @retry="load" />
    <template v-else>
      <div class="events-grid">
        <section class="panel">
          <div class="panel-heading"><div><h2><CalendarDays :size="18" />{{ view === 'timeline' ? '事件时间线' : '事件月历' }}</h2><p>{{ domainLabel(domain) }} · {{ filtered.length }} 个事件</p></div><div v-if="view === 'month'" class="month-nav"><button class="icon-btn" aria-label="上个月" @click="shiftMonth(-1)"><ArrowLeft :size="16" /></button><strong>{{ months }}</strong><button class="icon-btn" aria-label="下个月" @click="shiftMonth(1)"><ArrowRight :size="16" /></button></div></div>
          <div v-if="view === 'month'" class="calendar-scroll"><div class="calendar">
            <div v-for="day in ['一','二','三','四','五','六','日']" :key="day" class="calendar-weekday">周{{ day }}</div>
            <div v-for="day in dates" :key="day.date" class="calendar-day" :class="{ dim: day.dim }"><span>{{ day.display }}</span><button v-for="event in eventsOn(day.date)" :key="event.id" class="calendar-event" :title="event.title" @click="open(event)">{{ event.title }}</button></div>
          </div></div>
          <State v-else-if="!filtered.length" mode="empty" title="暂无匹配事件" detail="清除筛选或切换业务线查看更多事件。" />
          <div v-else class="event-timeline"><article v-for="event in filtered" :key="event.id" class="event-item"><div class="event-date">{{ event.start.slice(5) }}</div><span class="event-point"></span><button class="event-card" @click="open(event)"><div><span class="tag" :class="event.type === '大促' ? 'lavender' : 'amber'">{{ event.type }}</span><small>{{ domainLabel(event.domain) }}</small></div><h3>{{ event.title }}</h3><p>{{ event.note }}</p><div><span><Clock3 :size="13" />{{ event.start }} 至 {{ event.end }}</span><span v-if="event.scope.length"><MapPin :size="13" />{{ event.scope.join('、') }}</span></div></button></article></div>
        </section>
        <section class="panel event-trend">
          <div class="panel-heading"><div><h2>趋势叠加</h2><p>对照指标走势与事件时间范围。</p></div><button v-if="metric" class="icon-btn" :aria-label="showTable ? '显示趋势图' : '查看数据表'" @click="showTable = !showTable"><List :size="17" /></button></div>
          <div class="event-select"><el-select v-model="metricId" placeholder="选择核心指标" aria-label="趋势叠加指标" clearable><el-option v-for="item in metrics" :key="item.id" :label="item.name" :value="item.id" /></el-select></div>
          <State v-if="!metric" mode="empty" title="选择指标后查看趋势" />
          <div v-else-if="showTable" class="table-scroll event-select"><table class="data-table"><thead><tr><th>日期</th><th>指标值</th><th>事件</th></tr></thead><tbody><tr v-for="(date,index) in trendDates" :key="date"><td>{{ date }}</td><td>{{ number(metric.trend[index], metric.unit) }}</td><td>{{ eventsOn(date).filter(item => item.domain === metric?.domain).map(item => item.title).join('、') || '—' }}</td></tr></tbody></table></div>
          <Chart v-else :option="chart" :label="`${metric.name}走势与业务事件标记`" :height="226" />
        </section>
      </div>
    </template>
    <el-drawer v-model="drawer" :title="editing ? draft.id ? '编辑事件' : '新建事件' : '事件详情'" size="min(480px, 96vw)">
      <form v-if="editing" class="drawer-form" @submit.prevent="save">
        <label for="event-title">事件标题</label><el-input id="event-title" v-model="draft.title" />
        <label for="event-kind">事件类型</label><el-select id="event-kind" v-model="draft.type"><el-option v-for="kind in kinds" :key="kind" :label="kind" :value="kind" /></el-select>
        <label for="event-domain">指标域</label><el-select id="event-domain" v-model="draft.domain" :disabled="!!draft.id"><el-option v-for="choice in domains.slice(1)" :key="choice.id" :label="choice.label" :value="choice.id" /></el-select>
        <label for="event-start">开始日期</label><input id="event-start" v-model="draft.start" type="date">
        <label for="event-end">结束日期</label><input id="event-end" v-model="draft.end" type="date" :min="draft.start">
        <label v-if="!demoMode" for="event-scope-dimension">新增范围维度</label><el-select v-if="!demoMode" id="event-scope-dimension" v-model="draft.scopeDimension" placeholder="默认按品类"><el-option value="category" label="品类" /><el-option value="channel" label="渠道" /><el-option value="region" label="区域" /><el-option value="segment" label="客群" /></el-select>
        <label for="event-scope">影响范围</label><el-input id="event-scope" v-model="scopeText" placeholder="用逗号分隔品类、渠道或区域" />
        <label for="event-note">备注</label><el-input id="event-note" v-model="draft.note" type="textarea" :rows="4" />
        <p v-if="formError" class="form-error" role="alert">{{ formError }}</p><el-button type="primary" native-type="submit" :loading="pending">保存事件</el-button>
      </form>
      <div v-else-if="selected" class="event-detail"><span class="tag lavender">{{ selected.type }}</span><h2>{{ selected.title }}</h2><p>{{ selected.start }} 至 {{ selected.end }}</p><p>{{ domainLabel(selected.domain) }} · {{ selected.scope.join('、') || '全域' }}</p><p>{{ selected.note }}</p><p v-if="formError" class="form-error" role="alert">{{ formError }}</p><div v-if="canManage"><el-button type="primary" plain @click="open(selected, true)">编辑事件</el-button><el-button type="danger" plain :loading="pending" @click="remove">删除事件</el-button></div></div>
    </el-drawer>
  </div>
</template>
