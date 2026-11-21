<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDownToLine, ArrowLeft, Bell, Check, FileText, MessageSquareText, Printer, Send, Share2 } from 'lucide-vue-next'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, client, demoMode, demoUsers } from '../client'
import { canAnalyze, domain, errorText, user } from '../context'
import { domainLabel, number, type Format, type Report, type ReportSection } from '../model'
import State from '../components/State.vue'

const route = useRoute()
const router = useRouter()
const reports = ref<Report[]>([])
const report = ref<Report>()
const loading = ref(true)
const error = ref<unknown>()
const actionError = ref('')
const notice = ref('')
const exporting = ref(false)
const publishing = ref(false)
const commenting = ref(false)
const exportOpen = ref(false)
const format = ref<Format>('pdf')
const sectionIds = ref<string[]>([])
const sectionId = ref('')
const comment = ref('')
const quote = ref('')
const preview = ref<HTMLElement>()
const versions = computed(() => reports.value.filter(item => item.sessionId === report.value?.sessionId).sort((a, b) => b.version - a.version))
const sectionName = (id: string) => report.value?.sections.find(section => section.id === id)?.title ?? id
const formats: { id: Format; name: string }[] = [{ id: 'pdf', name: 'PDF' }, { id: 'xlsx', name: 'Excel' }, { id: 'md', name: 'Markdown' }]
const printMode = ref(false)
let generation = 0

async function load() {
  const current = ++generation
  loading.value = true
  error.value = undefined
  actionError.value = ''
  notice.value = ''
  quote.value = ''
  comment.value = ''
  report.value = undefined
  try {
    const items = await client.reports(domain.value)
    const id = route.params.id
    const active = typeof id === 'string' && id ? await client.report(id) : items[0]
    if (current !== generation) return
    reports.value = items
    report.value = active
    sectionId.value = active?.sections[0]?.id ?? ''
    if (active && route.query.export === 'pdf') {
      openExport('pdf')
      void router.replace({ name: 'reports', params: { id: active.id } })
    }
  } catch (failure) { if (current === generation) error.value = failure }
  finally { if (current === generation) loading.value = false }
}
watch([domain, () => route.params.id], load, { immediate: true })
function choose(id: string) { void router.push({ name: 'reports', params: { id } }) }
function replace(item: Report) {
  if (report.value?.id !== item.id) return
  report.value = item
  reports.value = reports.value.map(entry => entry.id === item.id ? item : entry)
}
function openExport(next: Format) {
  format.value = next
  sectionIds.value = report.value?.sections.map(section => section.id) ?? []
  actionError.value = ''
  exportOpen.value = true
}
async function exportReport() {
  if (!report.value || !sectionIds.value.length) return
  exporting.value = true; actionError.value = ''
  try {
    await client.exportReport(report.value, format.value, sectionIds.value)
    exportOpen.value = false
    notice.value = `${formats.find(item => item.id === format.value)?.name} 已生成。`
  } catch (failure) { actionError.value = errorText(failure) }
  finally { exporting.value = false }
}
async function publish() {
  if (!report.value) return
  publishing.value = true; actionError.value = ''
  try { replace(await client.publish(report.value.id)); notice.value = '报告已发布。' }
  catch (failure) { actionError.value = errorText(failure) }
  finally { publishing.value = false }
}
async function subscribe() {
  if (!report.value) return
  try {
    const updated = await client.subscribe(report.value.id, !report.value.subscribed)
    replace(updated)
    notice.value = updated.subscribed ? '已订阅此报告的周期简报。' : '已取消订阅。'
  } catch (failure) { actionError.value = errorText(failure) }
}
function captureSelection(section: ReportSection) {
  if (!canAnalyze.value) return
  const selection = window.getSelection()
  if (selection?.anchorNode && preview.value?.contains(selection.anchorNode)) {
    const text = selection.toString().trim().slice(0, 240)
    if (text) quote.value = text
  }
  sectionId.value = section.id
}
async function addComment() {
  if (!report.value || !comment.value.trim() || !sectionId.value) return
  commenting.value = true; actionError.value = ''
  try {
    replace(await client.comment(report.value.id, { section: sectionId.value, quote: quote.value || undefined, text: comment.value.trim() }))
    comment.value = ''; quote.value = ''
  } catch (failure) { actionError.value = errorText(failure) }
  finally { commenting.value = false }
}
function print() {
  printMode.value = true
  requestAnimationFrame(() => { window.print(); printMode.value = false })
}
</script>

<template>
  <div class="page reports-page" :class="{ printing: printMode }">
    <div class="page-heading"><div><h1>报告归档</h1><p>预览、协作与导出结构化经营归因报告。</p></div><RouterLink v-if="report && user?.role !== 'manager'" class="link-btn back-link" :to="{ name: 'workbench', params: { id: report.sessionId } }"><ArrowLeft :size="15" />返回归因会话</RouterLink></div>
    <State v-if="loading" mode="loading" />
    <State v-else-if="error" :mode="error instanceof ApiError && error.status === 403 ? 'forbidden' : 'error'" :detail="errorText(error)" retry @retry="load" />
    <div v-else-if="!report" class="panel"><State mode="empty" title="暂无可查阅的报告" :detail="canAnalyze ? '分析完成后，在工作台选择生成报告。' : '分析师发布后，报告将在此显示。'"><RouterLink v-if="canAnalyze" class="link-btn" :to="{ name: 'workbench' }">打开归因工作台</RouterLink></State></div>
    <template v-else>
      <div class="filter-bar wrap report-toolbar">
        <div class="filter-brand"><span class="filter-ico"><FileText :size="16" /></span><strong>V{{ report.version }}</strong><span class="tag" :class="report.status === 'published' ? 'green' : 'lavender'">{{ report.status === 'published' ? '已发布' : '草稿' }}</span></div>
        <div class="export-buttons push-right"><el-button v-for="item in formats" :key="item.id" @click="openExport(item.id)"><ArrowDownToLine :size="15" />导出 {{ item.name }}</el-button><el-button aria-label="打印报告" @click="print"><Printer :size="16" /></el-button><el-button v-if="canAnalyze && report.status === 'draft'" type="primary" :loading="publishing" @click="publish"><Share2 :size="15" />发布</el-button><el-button v-if="user?.role === 'manager'" :type="report.subscribed ? 'success' : 'primary'" plain @click="subscribe"><Bell :size="15" />{{ report.subscribed ? '已订阅' : '订阅简报' }}</el-button></div>
      </div>
      <p v-if="actionError && !exportOpen" class="form-error" role="alert">{{ actionError }}</p><p v-if="notice" class="inline-note" role="status"><Check :size="15" />{{ notice }}</p>
      <div class="reports-grid">
        <aside class="panel reports-index" aria-label="报告列表">
          <div class="panel-heading"><div><h2><FileText :size="17" />归档列表</h2><p>{{ reports.length }} 份报告</p></div></div>
          <button v-for="item in reports" :key="item.id" class="report-index-item" :aria-current="item.id === report.id ? 'true' : undefined" @click="choose(item.id)"><strong>{{ item.title }}</strong><small>V{{ item.version }} · {{ item.status === 'published' ? '已发布' : '草稿' }} · {{ item.updatedAt.slice(0, 10) }}</small></button>
          <div v-if="versions.length > 1" class="version-picker"><label for="report-version">查看历史版本</label><el-select id="report-version" :model-value="report.id" @change="choose"><el-option v-for="item in versions" :key="item.id" :label="`V${item.version}`" :value="item.id" /></el-select></div>
        </aside>
        <div class="report-paper-wrap" ref="preview">
          <article class="report-paper">
            <header><p>经营归因分析报告 · {{ domainLabel(report.domain) }}</p><h2>{{ report.title }}</h2><small>版本 {{ report.version }} · 更新于 {{ report.updatedAt.slice(0, 10) }}</small></header>
            <section v-for="section in report.sections" :id="`report-${section.id}`" :key="section.id" class="report-section" @mouseup="captureSelection(section)">
              <h3>{{ section.title }}</h3>
              <div v-for="paragraph in section.paragraphs" :key="paragraph" class="report-paragraph"><p>{{ paragraph.split('\n')[0] }}</p><pre v-if="paragraph.includes('\n')" class="code-block">{{ paragraph.split('\n').slice(1).join('\n') }}</pre></div>
              <div v-if="['drivers', 'factors'].includes(section.id) && section.rows?.length" class="report-bars" role="img" aria-label="各驱动因子贡献率条形图"><div v-for="row in section.rows" :key="row[0]"><span>{{ row[0] }}</span><div><i :style="{ width: `${Math.min(100, Math.abs(Number(row[2]) || 0))}%` }"></i></div><strong>{{ typeof row[2] === 'number' ? number(row[2], '%') : '—' }}</strong></div></div>
              <div v-if="section.headers && section.rows?.length" class="table-scroll"><table class="data-table"><thead><tr><th v-for="header in section.headers" :key="header">{{ header }}</th></tr></thead><tbody><tr v-for="(row, index) in section.rows" :key="index"><td v-for="(field, column) in row" :key="column">{{ typeof field === 'number' ? (section.headers?.[column] === 'p 值' ? field.toPrecision(3) : number(field)) : field }}</td></tr></tbody></table></div>
              <button v-if="canAnalyze" class="link-btn comment-link" @click="sectionId = section.id; quote = ''">批注本节</button>
            </section>
          </article>
        </div>
        <aside class="panel comments-panel" aria-label="报告批注">
          <div class="panel-heading"><div><h2><MessageSquareText :size="17" />批注</h2><p>{{ report.comments.length }} 条协作记录</p></div></div>
          <div v-if="report.comments.length" class="comment-list"><article v-for="item in report.comments" :key="item.id"><strong>{{ item.author }}</strong><small>{{ sectionName(item.section) }} · {{ item.createdAt.slice(0, 10) }}</small><blockquote v-if="item.quote">{{ item.quote }}</blockquote><p>{{ item.text }}</p></article></div>
          <p v-else class="comments-empty">暂无批注。</p>
          <form v-if="canAnalyze" class="comment-form" @submit.prevent="addComment">
            <label for="comment-section">批注章节</label><el-select id="comment-section" v-model="sectionId"><el-option v-for="section in report.sections" :key="section.id" :label="section.title" :value="section.id" /></el-select>
            <blockquote v-if="quote">{{ quote }} <button class="link-btn" type="button" @click="quote = ''">移除选文</button></blockquote>
            <el-input v-model="comment" type="textarea" :rows="3" aria-label="批注内容" placeholder="添加批注，用 @账号 提及同事" />
            <div v-if="demoMode && comment.endsWith('@')" class="chip-row"><button v-for="person in demoUsers.filter(item => item.id !== user?.id)" :key="person.id" class="chip" type="button" @click="comment += person.name + ' '">{{ person.name }}</button></div>
            <el-button native-type="submit" type="primary" :disabled="!comment.trim()" :loading="commenting"><Send :size="14" />提交批注</el-button>
          </form>
        </aside>
      </div>
    </template>
    <el-dialog v-model="exportOpen" title="选择导出章节" width="min(480px, 92vw)" :close-on-click-modal="!exporting" :show-close="!exporting">
      <p class="muted">导出为 {{ formats.find(item => item.id === format)?.name }}。</p>
      <el-checkbox-group v-model="sectionIds" class="export-sections"><el-checkbox v-for="section in report?.sections" :key="section.id" :value="section.id">{{ section.title }}</el-checkbox></el-checkbox-group>
      <p v-if="actionError" class="form-error" role="alert">{{ actionError }}</p>
      <template #footer><el-button :disabled="exporting" @click="exportOpen = false">取消</el-button><el-button type="primary" :disabled="!sectionIds.length" :loading="exporting" @click="exportReport"><ArrowDownToLine :size="15" />确认导出</el-button></template>
    </el-dialog>
  </div>
</template>
