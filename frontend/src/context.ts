import { computed, ref } from 'vue'
import { getIdentity, setIdentity } from './client'
import type { User } from './model'

export const identity = ref(getIdentity())
export const user = computed(() => identity.value?.user)
export const canAnalyze = computed(() => user.value?.role === 'analyst')
export const canManage = computed(() => user.value?.role === 'admin')
export const domain = ref(localStorage.getItem('attribution.domain') ?? 'all')
export const theme = ref(localStorage.getItem('attribution.theme') === 'dark' ? 'dark' : 'light')
export function signIn(next: { user: User; token?: string } | null) {
  identity.value = setIdentity(next)
  if (next && !next.user.domains.includes(domain.value)) domain.value = 'all'
}
export function changeDomain(next: string) {
  domain.value = next
  localStorage.setItem('attribution.domain', next)
}
export function applyTheme() {
  document.documentElement.classList.toggle('dark', theme.value === 'dark')
  localStorage.setItem('attribution.theme', theme.value)
}
export const errorText = (error: unknown) => error instanceof Error ? error.message : '操作失败，请稍后重试。'
