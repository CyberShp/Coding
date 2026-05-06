import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import { readFileSync } from 'fs'

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

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
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
