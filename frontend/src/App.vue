<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Activity, ArrowRight, BookOpen, CalendarDays, ChartNoAxesCombined, ChevronDown, ChevronsUpDown, CircleHelp, Command, FileText, LayoutDashboard, LogOut, Menu, Moon, Search, Sun, Workflow } from 'lucide-vue-next'
import { canAnalyze, changeDomain, domain, identity, signIn, theme, user, applyTheme } from './context'
import { client, dataPeriod } from './client'
import { baselineLabels, domainLabel, domains, roleLabels, type Metric } from './model'

const route = useRoute()
const router = useRouter()
const mobileMenu = ref(false)
const searchOpen = ref(false)
const helpOpen = ref(false)
const searchText = ref('')
const metrics = ref<Metric[]>([])
const searchError = ref('')
const navigation = [
  { name: 'dashboard', text: '指标异动大盘', icon: LayoutDashboard },
  { name: 'workbench', text: '归因分析工作台', icon: Workflow },
  { name: 'events', text: '业务事件日历', icon: CalendarDays },
  { name: 'dictionary', text: '指标字典', icon: BookOpen },
  { name: 'reports', text: '报告归档', icon: FileText },
]
const choices = computed(() => domains.filter(item => item.id === 'all' || user.value?.domains.includes(item.id)))
const searchResults = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  return [
    ...navigation.filter(item => item.text.toLowerCase().includes(keyword)).map(item => ({ id: item.name, name: item.text, label: '页面' })),
    ...metrics.value.filter(item => `${item.name} ${item.description}`.toLowerCase().includes(keyword)).map(item => ({ id: item.id, name: item.name, label: domainLabel(item.domain) })),
  ]
})
watch(() => route.fullPath, () => { mobileMenu.value = false })
watch(searchOpen, async open => {
  if (!open) return
  searchText.value = ''
  searchError.value = ''
  try { metrics.value = await client.metrics({ ...dataPeriod, domain: domain.value, baseline: 'mom' }) }
  catch { searchError.value = '指标搜索暂不可用。' }
})
function choose(id: string) {
  searchOpen.value = false
  if (navigation.some(item => item.name === id)) void router.push({ name: id })
  else void router.push({ name: 'dashboard', query: { metric: id } })
}
function toggleTheme() {
  theme.value = theme.value === 'light' ? 'dark' : 'light'
  applyTheme()
}
function logout() {
  signIn(null)
  void router.replace({ name: 'login' })
}
function openSearch(event: KeyboardEvent) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && identity.value) {
    event.preventDefault()
    searchOpen.value = !searchOpen.value
  }
}
window.addEventListener('keydown', openSearch)
</script>

<template>
  <RouterView v-if="route.name === 'login' || !user" />
  <div v-else class="shell" :class="{ 'menu-open': mobileMenu }">
    <button v-if="mobileMenu" class="mobile-scrim" aria-label="关闭导航" @click="mobileMenu = false"></button>
    <aside class="app-sidebar" aria-label="主导航">
      <RouterLink class="brand" :to="{ name: 'dashboard' }">
        <span class="brand-mark"><ChartNoAxesCombined :size="21" :stroke-width="2.5" /></span>
        <span class="brand-type"><strong>归因分析</strong><small>经营分析平台</small></span>
      </RouterLink>
      <nav class="app-nav">
        <span class="nav-label">工作空间</span>
        <RouterLink v-for="item in navigation" :key="item.name" :to="{ name: item.name }" :class="{ 'nav-active': route.name === item.name }" :title="item.text" :aria-current="route.name === item.name ? 'page' : undefined">
          <component :is="item.icon" :size="18" /><span>{{ item.text }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-footer">
        <button class="sidebar-help" @click="helpOpen = true"><CircleHelp :size="18" /><span>使用指南</span><ArrowRight :size="14" class="help-arrow" /></button>
      </div>
    </aside>
    <div class="app-main">
      <header class="topbar">
        <button class="icon-btn mobile-toggle" aria-label="打开导航" @click="mobileMenu = !mobileMenu"><Menu :size="21" /></button>
        <div class="breadcrumb"><span>工作空间</span><span class="slash">/</span><strong>{{ route.meta.title }}</strong></div>
        <div class="topbar-actions">
          <button class="search-trigger" aria-label="全局搜索" @click="searchOpen = true"><Search :size="16" /><span>搜索指标、页面</span><kbd><Command :size="11" /> K</kbd></button>
          <el-dropdown @command="changeDomain">
            <button class="domain-button"><span class="domain-icon"><Activity :size="14" /></span><span>{{ domainLabel(domain) }}</span><ChevronsUpDown :size="13" /></button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item v-for="choice in choices" :key="choice.id" :command="choice.id">{{ choice.label }}</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
          <button class="icon-btn theme-toggle" :aria-label="theme === 'light' ? '切换深色主题' : '切换浅色主题'" @click="toggleTheme"><Moon v-if="theme === 'light'" :size="18" /><Sun v-else :size="18" /></button>
          <span class="topbar-divider"></span>
          <el-dropdown @command="logout">
            <button class="profile-button" aria-label="账户菜单"><span class="avatar">{{ /^[a-z]/i.test(user.name) ? user.name[0].toUpperCase() : user.name.slice(-1) }}</span><span class="profile-name"><strong>{{ user.name }}</strong><small>{{ roleLabels[user.role] }}</small></span><ChevronDown :size="13" /></button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item command="logout"><LogOut :size="15" /> 退出登录</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </header>
      <main class="main-content">
        <RouterView />
      </main>
    </div>
    <el-dialog v-model="searchOpen" title="全局搜索" width="min(520px, 92vw)">
      <el-input v-model="searchText" autofocus placeholder="输入指标名称或页面" @keyup.enter="searchResults[0] && choose(searchResults[0].id)" />
      <p v-if="searchError" class="muted">{{ searchError }}</p>
      <div class="search-results">
        <button v-for="item in searchResults" :key="item.id" @click="choose(item.id)"><span>{{ item.name }}</span><small>{{ item.label }}</small><ArrowRight :size="14" /></button>
        <p v-if="!searchResults.length" class="muted">没有匹配结果。</p>
      </div>
    </el-dialog>
    <el-dialog v-model="helpOpen" title="使用指南" width="min(480px, 92vw)">
      <ol class="help-list">
        <li>在大盘选择业务线和时间周期，查看 {{ baselineLabels.mom }}、{{ baselineLabels.yoy }} 或目标差异。</li>
        <li v-if="canAnalyze">从异常指标发起归因，在工作台查看证据、继续追问或调整推演参数。</li>
        <li>在报告归档查看分析结论和可执行的行动建议。</li>
      </ol>
    </el-dialog>
  </div>
</template>
