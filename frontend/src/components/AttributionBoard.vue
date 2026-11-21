<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDownToLine, ArrowRight, ChartColumnIncreasing, Check, ChevronDown, ChevronRight, Code2, Expand, GitFork, List, Minimize, Save, Table2 } from 'lucide-vue-next'
import type { CustomSeriesOption } from 'echarts/charts'
import { client, ApiError } from '../client'
import { canAnalyze, errorText, theme } from '../context'
import { dimensions, number, rounded, type Analysis, type Dimension, type PivotRow, type Slice, type TreeNode } from '../model'
import Chart from './Chart.vue'
import State from './State.vue'
import WhatIf from './WhatIf.vue'

const props = defineProps<{ analysis: Analysis | null; fullscreen: boolean; refreshing?: boolean }>()
const emit = defineEmits<{ fullscreen: []; drill: [dimension: Dimension, slices: Slice[]]; refresh: []; report: [openExport?: boolean] }>()
const tabs = [{ id: 'waterfall', label: '贡献瀑布图' }, { id: 'tree', label: '杜邦拆解树' }, { id: 'pivot', label: '下钻透视表' }, { id: 'evidence', label: '结论与证据' }, { id: 'actions', label: '行动项' }, { id: 'whatif', label: 'What-If' }]
const active = ref('waterfall')
const alternative = ref(false)
const chartMode = ref<'trend' | 'sankey'>('trend')
const trend = ref<{ date: string; value: number | null }[]>([])
const trendError = ref('')
const trendLoading = ref(false)
const modal = ref(false)
const dimension = ref<Dimension>('channel')
const rows = ref<PivotRow[]>([])
const rowError = ref<unknown>()
const rowLoading = ref(false)
const openRows = ref<string[]>([])
const sort = ref<{ key: 'label' | 'previous' | 'current' | 'delta' | 'contribution'; descending: boolean }>({ key: 'delta', descending: false })
const notice = ref('')
const error = ref('')
const busy = ref(false)
const metric = computed(() => props.analysis?.metric)
const decomp = computed(() => props.analysis?.decomposition)
const unit = computed(() => metric.value?.unit)
const deltaUnit = computed(() => unit.value === '%' ? ' pp' : unit.value)
const diff = computed(() => decomp.value ? rounded(decomp.value.current - decomp.value.previous, 9) : 0)
const contribution = (value: number) => diff.value ? rounded(value / diff.value * 100) : null
const changed = computed(() => props.analysis?.messageCount && props.analysis.messageCount > 1 && props.analysis.status === 'completed')
const sorted = computed(() => [...rows.value].sort((a, b) => {
  const { key, descending } = sort.value
  const result = key === 'label' ? a.label.localeCompare(b.label, 'zh-CN') : (a[key] ?? 0) - (b[key] ?? 0)
  return result * (descending ? -1 : 1)
}))
const visibleRows = computed(() => sorted.value.flatMap(row => [{ ...row, level: 0 }, ...(openRows.value.includes(row.id) ? (row.children ?? []).map(child => ({ ...child, level: 1 })) : [])]))
const axisColor = computed(() => theme.value === 'dark' ? '#bfc8dc' : '#667088')
const gridColor = computed(() => theme.value === 'dark' ? '#343d58' : '#e9ebf4')

function switchTab(id: string) { active.value = id; alternative.value = false }
function tabKeys(event: KeyboardEvent, index: number) {
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1
  if (next < 0) return
  event.preventDefault()
  switchTab(tabs[next].id)
  document.getElementById(`board-tab-${tabs[next].id}`)?.focus()
}
watch(() => props.analysis?.id, () => { switchTab('waterfall'); rows.value = []; openRows.value = []; notice.value = ''; error.value = '' })
watch(() => props.analysis?.dimension, next => { if (next) dimension.value = next }, { immediate: true })
let trendVersion = 0
async function loadTrend() {
  const analysis = props.analysis
  if (!analysis?.metric || active.value !== 'evidence' || chartMode.value !== 'trend') return
  const generation = ++trendVersion
  trendLoading.value = true
  trendError.value = ''
  try {
    const points = await client.trend(analysis)
    if (generation === trendVersion) trend.value = points
  } catch (failure) { if (generation === trendVersion) trendError.value = errorText(failure) }
  finally { if (generation === trendVersion) trendLoading.value = false }
}
watch([active, chartMode, () => props.analysis?.id, () => props.analysis?.status], loadTrend)
let pivotVersion = 0
async function loadRows() {
  const analysis = props.analysis
  if (!analysis?.metric || active.value !== 'pivot') return
  const version = ++pivotVersion
  rowError.value = undefined
  rowLoading.value = true
  try {
    const result = await client.drilldown(analysis.id, dimension.value, analysis.slices, unit.value)
    if (version === pivotVersion && props.analysis?.id === analysis.id) rows.value = result
  } catch (failure) { if (version === pivotVersion) rowError.value = failure }
  finally { if (version === pivotVersion) rowLoading.value = false }
}
watch([active, dimension, () => props.analysis?.id, () => props.analysis?.slices.map(slice => slice.value).join('/'), () => props.analysis?.status], loadRows)
function flipRow(id: string) { openRows.value = openRows.value.includes(id) ? openRows.value.filter(item => item !== id) : [...openRows.value, id] }
function setSort(key: typeof sort.value.key) { sort.value = { key, descending: sort.value.key === key ? !sort.value.descending : false } }
function drill(row: PivotRow) {
  const slices = (props.analysis?.slices ?? []).filter(item => item.dimension !== row.dimension)
  emit('drill', row.dimension, [...slices, { dimension: row.dimension, value: row.label }])
}
function chooseNode(id: string) {
  dimension.value = id === 'visitors' || id === 'conversion' ? 'channel' : id === 'raw' || id === 'basket' ? 'category' : 'region'
  switchTab('pivot')
}
async function exportPivot() {
  if (!props.analysis) return
  try {
    const { exportLocal } = await import('../export')
    await exportLocal({ id: '', sessionId: props.analysis.id, title: `${metric.value?.name ?? '指标'}下钻透视表`, domain: props.analysis.domain, version: 1, status: 'draft', updatedAt: '', comments: [],
      sections: [{ id: 'pivot', title: '下钻透视表', paragraphs: [], headers: ['维度', '基期', '现期', '差额', '贡献率（%）'], rows: visibleRows.value.map(row => [row.label, row.previous ?? '—', row.current ?? '—', row.delta, row.contribution ?? '—']) }] }, 'xlsx', ['pivot'])
  } catch (failure) { error.value = errorText(failure) }
}
async function save() {
  if (!props.analysis) return
  busy.value = true; error.value = ''; notice.value = ''
  try { await client.snapshot(props.analysis.id); notice.value = '已保存分析快照。' }
  catch (failure) { error.value = errorText(failure) }
  finally { busy.value = false }
}

const waterfallRows = computed(() => {
  if (!decomp.value) return []
  let start = decomp.value.previous
  return [
    { name: '基期', from: 0, to: start, value: start, total: true },
    ...decomp.value.drivers.map(driver => {
      const beginning = start
      start += driver.value
      return { name: driver.name, from: beginning, to: start, value: driver.value, total: false }
    }),
    { name: '现期', from: 0, to: decomp.value.current, value: decomp.value.current, total: true },
  ]
})
const renderWaterfall: NonNullable<CustomSeriesOption['renderItem']> = (_params, api) => {
  const index = Number(api.value(0))
  const start = api.coord([index, api.value(1)])
  const end = api.coord([index, api.value(2)])
  const barWidth = 28
  const item = waterfallRows.value[index]
  const fill = item.total ? '#6658e9' : item.value < 0 ? '#dc637e' : '#26a583'
  const top = Math.min(start[1], end[1])
  return { type: 'rect', shape: { x: start[0] - barWidth / 2, y: top, width: barWidth, height: Math.max(2, Math.abs(start[1] - end[1])), r: 3 }, style: { fill } }
}
const waterfallOptions = computed(() => ({
  grid: { left: unit.value === '元' ? 68 : 45, right: 15, top: 25, bottom: 56 },
  tooltip: { trigger: 'item', renderMode: 'richText', formatter: (params: { dataIndex: number }) => {
    const row = waterfallRows.value[params.dataIndex]
    return `${row.name} · ${number(row.value, row.total ? unit.value : deltaUnit.value, !row.total)}${!row.total && diff.value ? ` · ${number(contribution(row.value), '%')}` : ''}`
  } },
  xAxis: { type: 'category', data: waterfallRows.value.map(item => item.name), axisLabel: { interval: 0, rotate: 16, color: axisColor.value, fontSize: 11, formatter: (value: string) => value.length > 5 ? value.slice(0, 5) + '\n' + value.slice(5) : value }, axisTick: { show: false } },
  yAxis: { type: 'value', axisLabel: { color: axisColor.value, formatter: (value: number) => unit.value === '元' && Math.abs(value) >= 10000 ? `${value / 10000}万` : number(value, unit.value === '%' ? '%' : '') }, splitLine: { lineStyle: { color: gridColor.value, type: 'dashed' } } },
  series: [{ type: 'custom', renderItem: renderWaterfall, encode: { x: 0, y: [1, 2] }, data: waterfallRows.value.map((row, index) => [index, row.from, row.to]) }],
}))
function mapTree(node: TreeNode): object {
  return { id: node.id, name: `${node.name}\n${number(node.current, node.unit)}`, children: node.children?.map(mapTree) }
}
function flatten(node: TreeNode, depth = 0): (TreeNode & { depth: number })[] {
  return [{ ...node, depth }, ...(node.children?.flatMap(child => flatten(child, depth + 1)) ?? [])]
}
const treeOptions = computed(() => ({
  tooltip: { trigger: 'item' },
  series: [{ type: 'tree', data: decomp.value ? [mapTree(decomp.value.tree)] : [], orient: 'LR', left: 32, right: 76, top: 22, bottom: 26, symbolSize: 11, initialTreeDepth: 3, expandAndCollapse: false, itemStyle: { color: '#6f61e9' }, lineStyle: { color: '#9b90e9' }, label: { position: 'top', color: axisColor.value, fontSize: 10 }, leaves: { label: { position: 'right', color: axisColor.value } } }],
}))
const evidenceChart = computed(() => {
  const target = metric.value?.name ?? '目标指标'
  if (chartMode.value === 'sankey') {
    const drivers = decomp.value?.drivers ?? []
    const links = drivers.filter(item => item.value !== 0).map(item => ({ source: item.name, target, value: Math.abs(item.value) }))
    return { tooltip: { trigger: 'item' }, series: [{ type: 'sankey', data: [...links.map(link => ({ name: link.source })), { name: target }], links, label: { color: axisColor.value, fontSize: 11 }, right: 78, nodeGap: 12, color: ['#8c7ff4', '#ac9fec', '#e897af', '#5547d3'] }] }
  }
  return { grid: { left: 67, right: 15, bottom: 29, top: 16 }, tooltip: { trigger: 'axis' }, xAxis: { type: 'category', data: trend.value.map(point => point.date.slice(5)), axisLabel: { color: axisColor.value } }, yAxis: { type: 'value', scale: true, axisLabel: { color: axisColor.value }, splitLine: { lineStyle: { color: gridColor.value } } }, series: [{ type: 'line', data: trend.value.map(point => point.value), showSymbol: false, lineStyle: { color: '#6b5ee9', width: 3 } }] }
})
</script>

<template>
  <section class="attribution-board" :class="{ 'board-fullscreen': fullscreen }" aria-label="动态归因看板">
    <header class="workbench-panel-heading"><div><span class="mini-icon lavender"><ChartColumnIncreasing :size="17" /></span><div><h2>归因看板</h2><small>量化结果与策略</small></div></div><button class="icon-btn" :aria-label="fullscreen ? '退出全屏' : '全屏看板'" @click="emit('fullscreen')"><Minimize v-if="fullscreen" :size="17" /><Expand v-else :size="17" /></button></header>
    <div class="board-tabs" role="tablist" aria-label="归因看板页签">
      <button v-for="(tab, index) in tabs" :id="`board-tab-${tab.id}`" :key="tab.id" role="tab" :tabindex="active === tab.id ? 0 : -1" :aria-selected="active === tab.id" aria-controls="board-tab-panel" @keydown="tabKeys($event, index)" @click="switchTab(tab.id)">{{ tab.label }}</button>
    </div>
    <div id="board-tab-panel" class="board-content" role="tabpanel" :aria-labelledby="`board-tab-${active}`">
      <State v-if="!analysis?.metric || !decomp" mode="empty" title="归因结果将在这里展示" detail="发起分析后可查看因子贡献、下钻证据与模拟结果。" />
      <template v-else>
        <div v-if="changed || refreshing" class="refresh-note"><Check :size="13" />{{ refreshing ? '证据更新中' : '看板已刷新' }}</div>
        <div v-if="active === 'waterfall'" class="board-stack">
          <div class="board-title"><div><h3>{{ metric?.name }}贡献瀑布图</h3><p>{{ decomp.method }} · 量化分析快照</p></div><button class="icon-btn" :aria-label="alternative ? '显示瀑布图' : '查看贡献数据表'" @click="alternative = !alternative"><List :size="17" /></button></div>
          <div class="reconcile"><span class="tag" :class="Math.abs(decomp.residual) <= 1e-9 ? 'green' : 'rose'"><Check v-if="Math.abs(decomp.residual) <= 1e-9" :size="13" />{{ Math.abs(decomp.residual) <= 1e-9 ? '贡献守恒' : '存在残差' }}</span><button class="link-btn" @click="modal = true"><Code2 :size="14" />查看口径 / SQL</button></div>
          <Chart v-if="!alternative" :option="waterfallOptions" label="基期、因子贡献与现期的瀑布图" :height="258" />
          <div class="table-scroll"><table class="data-table compact"><thead><tr><th>驱动因子</th><th>绝对贡献</th><th>贡献率</th></tr></thead><tbody><tr v-if="alternative"><td>基期</td><td>{{ number(decomp.previous, unit) }}</td><td>—</td></tr><tr v-for="driver in decomp.drivers" :key="driver.id"><td>{{ driver.name }}</td><td :class="{ danger: driver.value < 0, positive: driver.value > 0, 'change-cell': changed }">{{ number(driver.value, deltaUnit, true) }}</td><td>{{ number(contribution(driver.value), '%') }}</td></tr><tr><th>{{ alternative ? '现期' : '总变动' }}</th><th>{{ alternative ? number(decomp.current, unit) : number(diff, deltaUnit, true) }}</th><th>{{ diff && !alternative ? '100%' : '—' }}</th></tr></tbody></table></div>
        </div>
        <div v-else-if="active === 'tree'" class="board-stack">
          <div class="board-title"><div><h3><GitFork :size="17" />指标拆解树</h3><p>选择节点查看对应下钻维度。</p></div><button class="link-btn" @click="alternative = !alternative">{{ alternative ? '显示图表' : '查看数据表' }}</button></div>
          <Chart v-if="!alternative" :option="treeOptions" label="多层指标拆解树" :height="288" @select="chooseNode" />
          <div class="table-scroll"><table class="data-table compact"><thead><tr><th>指标</th><th>基期</th><th>现期</th><th>变动</th></tr></thead><tbody><tr v-for="node in flatten(decomp.tree)" :key="node.id"><td :style="{ paddingLeft: 8 + node.depth * 11 + 'px' }"><button class="link-btn" @click="chooseNode(node.id)">{{ node.name }}</button></td><td>{{ number(node.previous, node.unit) }}</td><td>{{ number(node.current, node.unit) }}</td><td>{{ number(rounded(node.current - node.previous), node.unit === '%' ? ' pp' : node.unit, true) }}</td></tr></tbody></table></div>
        </div>
        <div v-else-if="active === 'pivot'" class="board-stack">
          <div class="board-title"><div><h3><Table2 :size="17" />多维下钻透视</h3><p>展开层级，或选中一行继续追问。</p></div><button class="icon-btn" aria-label="导出当前透视表" :disabled="!rows.length" @click="exportPivot"><ArrowDownToLine :size="17" /></button></div>
          <div class="chip-row"><button v-for="(label, key) in dimensions" :key="key" class="chip" :aria-pressed="dimension === key" @click="dimension = key; openRows = []">{{ label }}</button></div>
          <State v-if="rowLoading" mode="loading" />
          <State v-else-if="rowError" :mode="rowError instanceof ApiError && rowError.status === 403 ? 'forbidden' : 'error'" :detail="errorText(rowError)" retry @retry="loadRows" />
          <State v-else-if="!rows.length" mode="empty" title="该切片的数据不足" />
          <div v-else class="table-scroll">
            <table class="data-table compact"><thead><tr><th v-for="column in [{ key: 'label', label: '维度' }, { key: 'previous', label: '基期' }, { key: 'current', label: '现期' }, { key: 'delta', label: '差额' }, { key: 'contribution', label: '贡献率' }] as const" :key="column.key" :aria-sort="sort.key !== column.key ? 'none' : sort.descending ? 'descending' : 'ascending'"><button class="table-sort" @click="setSort(column.key)">{{ column.label }}<small v-if="sort.key === column.key">{{ sort.descending ? '↓' : '↑' }}</small></button></th></tr></thead>
            <tbody><tr v-for="row in visibleRows" :key="row.id"><td><div class="pivot-label" :class="{ 'pivot-child': row.level }"><button v-if="row.children?.length" class="icon-btn tiny" :aria-expanded="openRows.includes(row.id)" :aria-label="`${openRows.includes(row.id) ? '折叠' : '展开'}${row.label}`" @click="flipRow(row.id)"><ChevronDown v-if="openRows.includes(row.id)" :size="13" /><ChevronRight v-else :size="13" /></button><button v-if="canAnalyze" class="link-btn" @click="drill(row)">{{ row.label }}</button><span v-else>{{ row.label }}</span></div></td><td>{{ number(row.previous, unit) }}</td><td>{{ number(row.current, unit) }}</td><td :class="row.delta < 0 ? 'danger' : 'positive'">{{ number(row.delta, deltaUnit, true) }}</td><td>{{ number(row.contribution, '%') }}</td></tr></tbody></table>
          </div>
          <button class="link-btn" @click="modal = true"><Code2 :size="14" />查看计算口径 / SQL</button>
        </div>
        <div v-else-if="active === 'evidence'" class="board-stack">
          <div class="board-title"><div><h3>核心归因结论</h3><p>综合定量验证与关联业务事件。</p></div></div>
          <State v-if="!analysis.conclusions.length" mode="empty" title="暂未形成归因结论" />
          <article v-for="item in analysis.conclusions" :key="item.id" class="evidence-card"><span class="tag" :class="item.type === '外部事件' ? 'amber' : 'lavender'">{{ item.type }}</span><h4>{{ item.title }}</h4><p>{{ item.text }}</p><RouterLink v-if="item.eventId" class="link-btn" :to="{ name: 'events', query: { event: item.eventId } }">查看业务事件 <ArrowRight :size="14" /></RouterLink></article>
          <div class="board-title"><div class="chip-row"><button class="chip" :aria-pressed="chartMode === 'trend'" @click="chartMode = 'trend'">下钻时序</button><button class="chip" :aria-pressed="chartMode === 'sankey'" @click="chartMode = 'sankey'">贡献流向</button></div><button class="link-btn" @click="alternative = !alternative">{{ alternative ? '显示图表' : '查看数据表' }}</button></div>
          <State v-if="chartMode === 'trend' && trendLoading" mode="loading" />
          <State v-else-if="chartMode === 'trend' && trendError" mode="error" :detail="trendError" retry @retry="loadTrend" />
          <State v-else-if="chartMode === 'trend' && !trend.length" mode="empty" title="暂无趋势数据" />
          <Chart v-else-if="!alternative" :option="evidenceChart" :label="chartMode === 'trend' ? '下钻时序图' : '贡献流向桑基图'" :height="210" />
          <div v-else class="table-scroll"><table class="data-table compact"><thead><tr><th>{{ chartMode === 'trend' ? '观测点' : '因子' }}</th><th>{{ chartMode === 'trend' ? '观测值' : '贡献' }}</th></tr></thead><tbody v-if="chartMode === 'trend'"><tr v-for="point in trend" :key="point.date"><td>{{ point.date }}</td><td>{{ number(point.value, unit) }}</td></tr></tbody><tbody v-else><tr v-for="item in decomp.drivers" :key="item.id"><td>{{ item.name }}</td><td>{{ number(item.value, deltaUnit, true) }}</td></tr></tbody></table></div>
        </div>
        <div v-else-if="active === 'actions'" class="board-stack">
          <div class="board-title"><div><h3>落地行动项</h3><p>按预计收益与可执行性排序。</p></div></div>
          <State v-if="!analysis.actions.length" mode="empty" title="暂无量化行动建议" />
          <article v-for="(action, index) in analysis.actions" :key="action.id" class="evidence-card"><span class="tag lavender">优先级 {{ index + 1 }}</span><h4>{{ action.title }}</h4><p>{{ action.description }}</p><dl class="action-meta"><div><dt>驱动因子</dt><dd>{{ action.driver }}</dd></div><div><dt>责任岗位</dt><dd>{{ action.owner }}</dd></div><div><dt>预计周期</dt><dd>{{ action.days }} 天</dd></div><div><dt>预期挽回</dt><dd>{{ number(action.recovery, '元') }}</dd></div></dl></article>
        </div>
        <WhatIf v-else :analysis="analysis" @refresh="emit('refresh')" />
      </template>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="notice" class="inline-note" role="status">{{ notice }}</p>
    </div>
    <footer v-if="canAnalyze" class="board-footer"><el-button :disabled="!decomp" :loading="busy" @click="save"><Save :size="15" /> 保存快照</el-button><el-button type="primary" :disabled="analysis?.status !== 'completed'" @click="emit('report')">生成报告</el-button><el-button :disabled="analysis?.status !== 'completed'" @click="emit('report', true)"><ArrowDownToLine :size="15" /> 导出</el-button></footer>
    <el-dialog v-model="modal" title="指标口径与查询" width="min(610px, 92vw)" append-to-body><p>{{ metric?.description }} · {{ decomp?.method }}</p><pre class="code-block">{{ decomp?.sql }}</pre></el-dialog>
  </section>
</template>
