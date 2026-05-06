import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
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
        target: 'ws://localhost:8001',
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
