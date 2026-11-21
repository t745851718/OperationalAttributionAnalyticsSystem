<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, ChartNoAxesCombined, ChartColumnIncreasing, ShieldCheck, Workflow } from 'lucide-vue-next'
import { client } from '../client'
import { errorText, signIn } from '../context'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const pending = ref(false)
async function login() {
  if (pending.value) return
  pending.value = true
  error.value = ''
  try {
    signIn(await client.login(username.value, password.value))
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') && !route.query.next.startsWith('//') ? route.query.next : '/'
    await router.replace(next)
  } catch (failure) { error.value = errorText(failure) }
  finally { pending.value = false }
}
</script>

<template>
  <main class="login-layout">
    <section class="login-hero">
      <div class="login-brand"><span class="brand-mark"><ChartNoAxesCombined :size="24" /></span><strong>经营归因分析系统</strong></div>
      <div class="login-copy">
        <h1>经营指标归因<br>与情景推演</h1>
        <p>从指标监控到量化证据，在同一工作台完成经营归因、情景推演和行动决策。</p>
        <ul><li><ChartColumnIncreasing :size="17" />多层指标拆解</li><li><Workflow :size="17" />可追溯的验证证据</li><li><ShieldCheck :size="17" />按角色管理工作空间</li></ul>
      </div>
      <div class="hero-chart" aria-hidden="true"><i v-for="height in [22, 34, 29, 44, 38, 57, 48, 65, 53, 76, 68, 96]" :key="height" :style="{ height: height + '%' }"></i></div>
    </section>
    <section class="login-form-area">
      <form class="login-form" @submit.prevent="login()">
        <h2>登录工作空间</h2>
        <p>登录后查看您有权访问的指标与分析报告。</p>
        <label for="username">账号</label>
        <el-input id="username" v-model="username" autocomplete="username" placeholder="输入账号" size="large" required />
        <label for="password">密码</label>
        <el-input id="password" v-model="password" type="password" show-password autocomplete="current-password" placeholder="输入密码" size="large" required />
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <el-button native-type="submit" type="primary" size="large" :loading="pending" class="login-submit">登录 <ArrowRight :size="16" /></el-button>
      </form>
    </section>
  </main>
</template>
