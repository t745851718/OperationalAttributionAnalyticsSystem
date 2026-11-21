<script setup lang="ts">
import { AlertCircle, Inbox, ShieldAlert } from 'lucide-vue-next'
defineProps<{ mode: 'loading' | 'error' | 'empty' | 'forbidden'; title?: string; detail?: string; retry?: boolean }>()
defineEmits<{ retry: [] }>()
</script>

<template>
  <div v-if="mode === 'loading'" class="state" aria-label="正在加载" aria-busy="true"><el-skeleton :rows="4" animated /></div>
  <div v-else class="state" :role="mode === 'empty' ? 'status' : 'alert'">
    <span class="state-icon"><Inbox v-if="mode === 'empty'" :size="24" /><ShieldAlert v-else-if="mode === 'forbidden'" :size="24" /><AlertCircle v-else :size="24" /></span>
    <strong>{{ title ?? (mode === 'empty' ? '暂无数据' : mode === 'forbidden' ? '无访问权限' : '加载失败') }}</strong>
    <p v-if="detail">{{ detail }}</p>
    <el-button v-if="retry" @click="$emit('retry')">重试</el-button>
    <slot />
  </div>
</template>
