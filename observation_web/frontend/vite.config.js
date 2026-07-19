import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { readFileSync } from 'fs'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

// Read backend port from project config.json — single source of truth.
// Falls back to 8002 if the file is missing or malformed.
function getBackendPort() {
  try {
    const cfg = JSON.parse(readFileSync(path.resolve(__dirname, '../config.json'), 'utf-8'))
    return cfg?.server?.port ?? 8002
  } catch {
    return 8002
  }
}

const backendPort = getBackendPort()

// Set of all @element-plus/icons-vue component names, used by the custom
// resolver below so icons referenced in templates (e.g. <Refresh />) are
// auto-imported on demand instead of being globally registered in main.js.
const elIconNames = new Set(Object.keys(ElementPlusIconsVue))

function ElementPlusIconsResolver() {
  return {
    type: 'component',
    resolve(name) {
      if (elIconNames.has(name)) {
        return { name, from: '@element-plus/icons-vue' }
      }
    },
  }
}

export default defineConfig({
  plugins: [
    vue(),
    // Auto-import Element Plus JS APIs (ElMessage, ElMessageBox, ...) on demand.
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: false,
    }),
    // Auto-import Element Plus components + icons on demand (with their styles).
    Components({
      resolvers: [ElementPlusResolver(), ElementPlusIconsResolver()],
      dts: false,
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            // Order matters: vue-echarts/zrender contain "vue"/"echarts" —
            // classify the charting stack first.
            if (
              id.includes('echarts') ||
              id.includes('vue-echarts') ||
              id.includes('zrender')
            ) {
              return 'vendor-echarts'
            }
            if (id.includes('element-plus')) {
              return 'vendor-element-plus'
            }
            if (
              id.includes('/vue/') ||
              id.includes('/@vue/') ||
              id.includes('vue-router') ||
              id.includes('pinia')
            ) {
              return 'vendor-vue'
            }
          }
        },
      },
    },
  },
  server: {
    port: 5174,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            const clientIp = req.socket?.remoteAddress?.replace('::ffff:', '') || 'unknown'
            proxyReq.setHeader('X-Forwarded-For', clientIp)
            proxyReq.setHeader('X-Real-IP', clientIp)
          })
        },
      },
      '/ws': {
        target: `ws://localhost:${backendPort}`,
        ws: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            const clientIp = req.socket?.remoteAddress?.replace('::ffff:', '') || 'unknown'
            proxyReq.setHeader('X-Forwarded-For', clientIp)
            proxyReq.setHeader('X-Real-IP', clientIp)
          })
        },
      },
    },
  },
})
