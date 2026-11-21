import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { ElButton, ElCheckbox, ElCheckboxGroup, ElDatePicker, ElDialog, ElDrawer, ElDropdown, ElDropdownItem, ElDropdownMenu, ElInput, ElOption, ElSelect, ElSkeleton } from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './style.css'
import App from './App.vue'
import { applyTheme, identity, signIn } from './context'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('./pages/Dashboard.vue'), meta: { title: '指标异动大盘' } },
    { path: '/workbench/:id?', name: 'workbench', component: () => import('./pages/Workbench.vue'), meta: { title: '归因分析工作台' } },
    { path: '/events', name: 'events', component: () => import('./pages/Events.vue'), meta: { title: '业务事件日历' } },
    { path: '/dictionary', name: 'dictionary', component: () => import('./pages/Dictionary.vue'), meta: { title: '指标字典' } },
    { path: '/reports/:id?', name: 'reports', component: () => import('./pages/Reports.vue'), meta: { title: '报告归档' } },
    { path: '/login', name: 'login', component: () => import('./pages/Login.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
router.beforeEach(to => {
  if (to.name !== 'login' && !identity.value) return { name: 'login', query: { next: to.fullPath } }
  if (to.name === 'login' && identity.value) return { name: 'dashboard' }
})
window.addEventListener('attribution:logout', () => {
  signIn(null)
  void router.replace({ name: 'login' })
})
applyTheme()
const app = createApp(App).use(router)
for (const component of [ElButton, ElCheckbox, ElCheckboxGroup, ElDatePicker, ElDialog, ElDrawer, ElDropdown, ElDropdownItem, ElDropdownMenu, ElInput, ElOption, ElSelect, ElSkeleton]) {
  app.component(component.name!, component)
}
app.mount('#app')
