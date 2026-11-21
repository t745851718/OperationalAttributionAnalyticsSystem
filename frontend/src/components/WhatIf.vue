<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Plus, SlidersHorizontal, Trash2 } from 'lucide-vue-next'
import { client } from '../client'
import { canAnalyze, errorText } from '../context'
import { number, type Analysis, type Scenario } from '../model'
import Chart from './Chart.vue'
import State from './State.vue'

const props = defineProps<{ analysis: Analysis }>()
const emit = defineEmits<{ refresh: [] }>()
const drivers = computed(() => props.analysis.decomposition?.drivers.filter(driver => driver.adjustable) ?? [])
const params = ref<Record<string, number>>({})
const result = ref<Scenario>()
const error = ref('')
const pending = ref(false)
const saving = ref(false)
const tabular = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let controller: AbortController | undefined
const unit = computed(() => props.analysis.metric?.unit)
const deltaUnit = computed(() => unit.value === '%' ? ' pp' : unit.value)
const name = computed(() => {
  const used = new Set(props.analysis.scenarios.map(item => item.name))
  return ['情景 A', '情景 B', '情景 C'].find(item => !used.has(item)) ?? '新情景'
})
const comparison = computed(() => ({
  grid: { left: 88, right: 24, bottom: 34, top: 16 },
  xAxis: { type: 'category', data: props.analysis.scenarios.map(item => item.name) },
  yAxis: { type: 'value', scale: true },
  tooltip: { trigger: 'axis', valueFormatter: (value: number) => number(value, unit.value) },
  series: [{ type: 'bar', barMaxWidth: 40, data: props.analysis.scenarios.map(item => item.estimate), itemStyle: { color: '#8072eb', borderRadius: [5, 5, 0, 0] } },
    { type: 'scatter', name: '80% 下界', data: props.analysis.scenarios.map(item => item.low), itemStyle: { color: '#293983' } },
    { type: 'scatter', name: '80% 上界', data: props.analysis.scenarios.map(item => item.high), itemStyle: { color: '#1f896c' } }],
}))
const curve = computed(() => ({
  grid: { left: 88, right: 25, bottom: 33, top: 16 },
  xAxis: { type: 'category', data: result.value?.curve.map(point => `${point[0]}%`) ?? [] },
  yAxis: { type: 'value', scale: true },
  tooltip: { trigger: 'axis', valueFormatter: (value: number) => number(value, unit.value) },
  series: [{ type: 'line', data: result.value?.curve.map(point => point[1]), smooth: true, lineStyle: { color: '#6557e9', width: 3 }, itemStyle: { color: '#6557e9' }, areaStyle: { color: '#8b7cea21' } }],
}))
async function simulate() {
  const active = new AbortController()
  controller = active
  try {
    const response = await client.simulate(props.analysis.id, { ...params.value }, name.value, false, active.signal, unit.value)
    if (!active.signal.aborted) result.value = response
  } catch (failure) {
    if (!active.signal.aborted) error.value = errorText(failure)
  } finally { if (!active.signal.aborted) pending.value = false }
}
function schedule() {
  controller?.abort()
  clearTimeout(timer)
  if (!canAnalyze.value || !drivers.value.length) return
  error.value = ''
  pending.value = true
  timer = setTimeout(simulate, 170)
}
watch(() => props.analysis.id, () => {
  params.value = Object.fromEntries(drivers.value.map(driver => [driver.id, 0]))
  result.value = undefined
}, { immediate: true })
watch(params, schedule, { deep: true, immediate: true })
onBeforeUnmount(() => { clearTimeout(timer); controller?.abort() })
async function save() {
  saving.value = true
  try { await client.simulate(props.analysis.id, { ...params.value }, name.value, true, undefined, unit.value); emit('refresh') }
  catch (failure) { error.value = errorText(failure) }
  finally { saving.value = false }
}
async function remove(id: string) {
  try { await client.removeScenario(props.analysis.id, id); emit('refresh') }
  catch (failure) { error.value = errorText(failure) }
}
</script>

<template>
  <div class="board-stack">
    <div class="board-title"><div><h3><SlidersHorizontal :size="17" />情景模拟</h3><p>调整可干预因子，观察预测值及 80% 区间。</p></div><button class="link-btn" @click="tabular = !tabular">{{ tabular ? '切换图表' : '查看数据表' }}</button></div>
    <p v-if="error" class="form-error" role="alert">{{ error }} <button class="link-btn" @click="schedule">重试</button></p>
    <State v-if="!drivers.length" mode="empty" title="没有可干预的因子" />
    <div v-else-if="canAnalyze" class="sliders">
      <div v-for="driver in drivers" :key="driver.id" class="slider-row">
        <label :for="`adjust-${driver.id}`">{{ driver.name }} <small>基准 {{ number(driver.current, driver.unit) }}</small></label>
        <div><input :id="`adjust-${driver.id}`" v-model.number="params[driver.id]" type="range" :min="driver.min" :max="driver.max" step="1"><output>{{ number(params[driver.id] ?? 0, '%', true) }}</output></div>
        <small class="muted">建议范围 {{ driver.min }}% 至 +{{ driver.max }}%</small>
      </div>
    </div>
    <div v-if="result && canAnalyze" class="prediction" :aria-busy="pending">
      <div><span>预测值</span><strong>{{ number(result.estimate, unit) }}</strong></div><div><span>预期变化</span><strong>{{ number(result.change, deltaUnit, true) }}</strong></div>
      <small>80% 区间 {{ number(result.low, unit) }} 至 {{ number(result.high, unit) }}</small>
      <el-button type="primary" plain :disabled="pending || analysis.scenarios.length >= 3" :loading="saving" @click="save"><Plus :size="15" />保存{{ name }}</el-button>
    </div>
    <div v-if="result" class="chart-box">
      <h4>敏感度曲线</h4>
      <div v-if="tabular" class="table-scroll"><table class="data-table"><thead><tr><th>因子调整</th><th>预测值</th></tr></thead><tbody><tr v-for="point in result.curve" :key="point[0]"><td>{{ point[0] }}%</td><td>{{ number(point[1], unit) }}</td></tr></tbody></table></div>
      <Chart v-else :option="curve" label="因子敏感度曲线" :height="156" />
    </div>
    <div class="chart-box">
      <h4>已保存情景 <small>{{ analysis.scenarios.length }} / 3</small></h4>
      <Chart v-if="analysis.scenarios.length > 1 && !tabular" :option="comparison" label="已保存情景点估计与区间" :height="175" />
      <div v-if="analysis.scenarios.length" class="scenario-list"><article v-for="item in analysis.scenarios" :key="item.id"><div><strong>{{ item.name }}</strong><small>{{ number(item.low, unit) }} – {{ number(item.high, unit) }}</small></div><strong>{{ number(item.estimate, unit) }}</strong><button v-if="canAnalyze" class="icon-btn" :aria-label="`移除${item.name}`" @click="remove(item.id)"><Trash2 :size="15" /></button></article></div>
      <p v-else class="muted">暂无已保存情景。</p>
    </div>
  </div>
</template>
