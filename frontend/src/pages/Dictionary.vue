<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { BookOpen, Braces, ChevronDown, ChevronRight, GitFork, Plus, Save } from 'lucide-vue-next'
import { ElMessageBox } from 'element-plus'
import { ApiError, client, demoMode } from '../client'
import { canManage, domain, errorText } from '../context'
import { references, unitOptions, validateDefinition } from '../formula'
import { domainLabel, domains, type MetricDefinition } from '../model'
import State from '../components/State.vue'

const definitions = ref<MetricDefinition[]>([])
const selected = ref('')
const folded = ref<string[]>([])
const draft = ref<MetricDefinition>()
const loading = ref(true)
const error = ref<unknown>()
const failed = ref('')
const note = ref('')
const pending = ref(false)
const dragging = ref<string>()
const reference = ref('')
const factFields = computed(() => draft.value?.domain === 'fmcg'
  ? [{ id: 'revenue', name: '营业收入' }, { id: 'materials', name: '原料成本' }, { id: 'logistics', name: '物流履约费' }, { id: 'commission', name: '渠道佣金' }, { id: 'units', name: '销量' }]
  : [{ id: 'visits', name: '访客数' }, { id: 'orders', name: '订单数' }, { id: 'gmv', name: '订单实付金额' }, { id: 'stockouts', name: '断货访客数' }, { id: 'promo_orders', name: '促销订单数' }])
const sourceField = computed(() => draft.value?.sourceField ?? (draft.value?.id === 'sales' ? 'gmv' : draft.value?.id))
function selectSource(field: string) {
  if (!draft.value) return
  draft.value.sourceField = field
  draft.value.unit = ['visits', 'stockouts'].includes(field) ? '人' : ['orders', 'promo_orders'].includes(field) ? '单' : field === 'units' ? '件' : '元'
}
const options = computed(() => definitions.value.filter(item => item.id !== draft.value?.id && item.domain === draft.value?.domain))
const preview = computed(() => draft.value ? references(draft.value.formula).map(id => ({ id, name: options.value.find(item => item.id === id)?.name ?? id, valid: options.value.some(item => item.id === id) })) : [])
const children = (parent: string | null) => definitions.value.filter(item => item.parentId === parent).sort((a, b) => a.order - b.order)
const visible = computed(() => {
  function walk(parent: string | null, depth = 0, seen = new Set<string>()): { item: MetricDefinition; depth: number; hasChildren: boolean }[] {
    return children(parent).filter(item => !seen.has(item.id)).flatMap(item => {
      const entry = { item, depth, hasChildren: children(item.id).length > 0 }
      return folded.value.includes(item.id) ? [entry] : [entry, ...walk(item.id, depth + 1, new Set([...seen, item.id]))]
    })
  }
  return walk(null)
})
let version = 0
async function load() {
  const active = ++version
  loading.value = true
  error.value = undefined
  try {
    const items = await client.definitions(domain.value)
    if (active !== version) return
    definitions.value = items
    const item = items.find(item => item.id === selected.value) ?? items.find(item => item.parentId === null)
    if (item) select(item)
    else { draft.value = undefined; selected.value = '' }
  } catch (failure) { if (active === version) error.value = failure }
  finally { if (active === version) loading.value = false }
}
watch(domain, load, { immediate: true })
function select(item: MetricDefinition) {
  selected.value = item.id
  draft.value = { ...item }
  failed.value = ''; note.value = ''; reference.value = ''
}
function create() {
  const item: MetricDefinition = { id: '', name: '', domain: domain.value === 'all' ? 'commerce' : domain.value, unit: '元', type: '原子', model: 'add', formula: '', parentId: null, order: definitions.value.length }
  select(item)
}
function fold(id: string) {
  folded.value = folded.value.includes(id) ? folded.value.filter(item => item !== id) : [...folded.value, id]
}
function insert(value: string) {
  if (draft.value) draft.value.formula = [draft.value.formula.trimEnd(), value].filter(Boolean).join(' ')
}
function persistLocal(item: MetricDefinition) {
  definitions.value = [...definitions.value.filter(entry => entry.id !== item.id), item]
  select(item)
  note.value = '已保存指标定义。'
}
async function persist(item: MetricDefinition) {
  failed.value = ''; note.value = ''
  pending.value = true
  try {
    validateDefinition(item, definitions.value)
    persistLocal(await client.saveDefinition(item))
  } catch (failure) { failed.value = errorText(failure) }
  finally { pending.value = false }
}
function drop(parentId: string | null) {
  const item = definitions.value.find(entry => entry.id === dragging.value)
  dragging.value = undefined
  if (item && canManage.value && item.id !== parentId && !pending.value) void persist({ ...item, parentId })
}
async function remove() {
  const definition = draft.value
  if (!definition?.id) return
  try { await ElMessageBox.confirm(`删除「${definition.name}」？`, '删除指标', { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }) }
  catch { return }
  pending.value = true; failed.value = ''
  try { await client.removeDefinition(definition); await load() }
  catch (failure) { failed.value = errorText(failure) }
  finally { pending.value = false }
}
</script>

<template>
  <div class="page">
    <div class="page-heading"><div><h1>指标字典</h1><p>管理指标口径、计算公式与默认拆解层级。</p></div><el-button v-if="canManage" type="primary" class="primary-cta" @click="create"><Plus :size="17" />新建指标</el-button></div>
    <State v-if="loading" mode="loading" />
    <State v-else-if="error" :mode="error instanceof ApiError && error.status === 403 ? 'forbidden' : 'error'" :detail="errorText(error)" retry @retry="load" />
    <div v-else class="dictionary-grid">
      <section class="panel dictionary-tree">
        <div class="panel-heading"><div><h2><BookOpen :size="18" />指标体系</h2><p>{{ domainLabel(domain) }} · {{ definitions.length }} 项指标</p></div></div>
        <div v-if="canManage" class="drop-root" @dragover.prevent @drop.prevent="drop(null)">拖至此处设为顶层指标</div>
        <State v-if="!visible.length" mode="empty" title="此业务线暂无指标" />
        <div v-else class="definition-list">
          <div v-for="{item, depth, hasChildren} in visible" :key="item.id" class="definition-row" :class="{ selected: selected === item.id }" :style="{ paddingLeft: 12 + depth * 15 + 'px' }" :draggable="canManage" @dragstart="dragging = item.id" @dragend="dragging = undefined" @dragover.prevent @drop.prevent="drop(item.id)">
            <button v-if="hasChildren" class="icon-btn tiny" :aria-expanded="!folded.includes(item.id)" :aria-label="`${folded.includes(item.id) ? '展开' : '折叠'}${item.name}`" @click="fold(item.id)"><ChevronRight v-if="folded.includes(item.id)" :size="15" /><ChevronDown v-else :size="15" /></button><span v-else class="tree-spacer"></span>
            <button class="definition-select" :aria-current="selected === item.id ? 'true' : undefined" @click="select(item)">{{ item.name }} <small>{{ item.type }}</small></button>
          </div>
        </div>
      </section>
      <section class="panel dictionary-form">
        <div class="panel-heading"><div><h2><Braces :size="18" />{{ draft?.id ? '指标详情' : '新建指标' }}</h2><p>{{ canManage ? '编辑公式与指标树的父子关系。' : '可查阅指标定义与所引用的计算口径。' }}</p></div><span v-if="!canManage" class="tag neutral">只读</span></div>
        <State v-if="!draft" mode="empty" title="请选择一个指标" />
        <form v-else class="metric-form" @submit.prevent="persist(draft)">
          <div class="metric-form-grid">
            <div><label for="metric-title">指标名称</label><el-input id="metric-title" v-model="draft.name" :disabled="!canManage" /></div>
            <div><label for="metric-domain">指标域</label><el-select id="metric-domain" v-model="draft.domain" :disabled="!canManage || !!draft.id" @change="draft.parentId = null"><el-option v-for="choice in domains.slice(1)" :key="choice.id" :value="choice.id" :label="choice.label" /></el-select></div>
            <div><label for="metric-type">类型</label><el-select id="metric-type" v-model="draft.type" :disabled="!canManage"><el-option v-for="value in ['原子','派生','复合']" :key="value" :value="value" :label="value" /></el-select></div>
            <div><label for="metric-unit">单位</label><el-select id="metric-unit" v-model="draft.unit" :disabled="!canManage"><el-option v-for="value in unitOptions" :key="value" :value="value" :label="value" /></el-select></div>
            <div><label for="metric-model">拆解模型</label><el-select id="metric-model" v-model="draft.model" :disabled="!canManage"><el-option value="add" label="加法模型" /><el-option value="mul" label="乘法模型" /></el-select></div>
            <div v-if="!demoMode && draft.type === '原子'"><label for="metric-source">事实字段</label><el-select id="metric-source" :model-value="sourceField" :disabled="!canManage" placeholder="选择事实字段" @change="selectSource"><el-option v-for="field in factFields" :key="field.id" :value="field.id" :label="field.name" /></el-select></div>
            <div><label for="metric-parent">父级指标</label><el-select id="metric-parent" :model-value="draft.parentId ?? ''" :disabled="!canManage" @change="draft.parentId = $event || null"><el-option value="" label="顶层指标" /><el-option v-for="option in options" :key="option.id" :value="option.id" :label="option.name" /></el-select></div>
          </div>
          <label for="metric-formula">拆解公式</label>
          <div v-if="canManage" class="formula-tools"><el-select v-model="reference" placeholder="插入指标引用" aria-label="插入指标引用" @change="insert($event); reference = ''"><el-option v-for="item in options" :key="item.id" :value="item.id" :label="`${item.name} · ${item.id}`" /></el-select><button v-for="operator in ['+', '−', '×', '÷', '(', ')']" :key="operator" type="button" class="icon-btn" :aria-label="`插入 ${operator}`" @click="insert(operator)">{{ operator }}</button></div>
          <el-input id="metric-formula" v-model="draft.formula" type="textarea" :rows="3" :readonly="!canManage" placeholder="原子指标可留空" class="formula-input" />
          <div class="formula-preview"><h3><GitFork :size="16" />拆解预览</h3><div><span class="tag lavender">{{ draft.name || '新指标' }}</span><ChevronRight v-if="preview.length" :size="15" /><span v-for="item in preview" :key="item.id" class="tag" :class="item.valid ? 'neutral' : 'rose'">{{ item.name }}</span><span v-if="!preview.length" class="muted">暂无引用指标</span></div></div>
          <p v-if="failed" class="form-error" role="alert">{{ failed }}</p><p v-if="note" class="inline-note" role="status">{{ note }}</p>
          <div v-if="canManage" class="form-buttons"><el-button type="primary" native-type="submit" :loading="pending"><Save :size="15" />保存指标</el-button><el-button v-if="draft.id" type="danger" plain :disabled="pending" @click="remove">删除指标</el-button></div>
        </form>
      </section>
    </div>
  </div>
</template>
