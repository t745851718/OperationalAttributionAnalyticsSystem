import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  return {
    plugins: [vue()],
    cacheDir: `node_modules/.vite-${mode}`,
    optimizeDeps: { include: ['exceljs', 'html2canvas', 'jspdf'] },
    server: {
      proxy: { '/api': env.VITE_API_TARGET || 'http://127.0.0.1:8000' },
    },
    preview: {
      proxy: { '/api': env.VITE_API_TARGET || 'http://127.0.0.1:8000' },
    },
  }
})
