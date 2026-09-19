import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = process.env.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET

  return {
    plugins: [vue()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: proxyTarget || 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
