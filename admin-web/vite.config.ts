import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/docs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/redoc': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/openapi.json': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  esbuild: {
    drop: ['console', 'debugger'],
  },
  build: {
    target: 'es2020',
    cssCodeSplit: true,
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (
            id.includes('/node_modules/vue/') ||
            id.includes('/node_modules/@vue/') ||
            id.includes('/node_modules/vue-router/') ||
            id.includes('/node_modules/pinia/')
          ) {
            return 'vue-vendor'
          }
          if (id.includes('/node_modules/@element-plus/icons-vue/')) {
            return 'ep-icons'
          }
          if (
            id.includes('/node_modules/element-plus/') ||
            id.includes('/node_modules/@floating-ui/') ||
            id.includes('/node_modules/@popperjs/') ||
            id.includes('/node_modules/lodash-es/') ||
            id.includes('/node_modules/async-validator/') ||
            id.includes('/node_modules/@ctrl/tinycolor/')
          ) {
            return 'element-plus'
          }
          return undefined
        },
      },
    },
  },
})
