import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
  },
  {
    path: '/config',
    name: 'Configuration',
    component: () => import('@/views/Config.vue'),
  },
  {
    path: '/session',
    name: 'Session',
    component: () => import('@/views/Session.vue'),
  },
  {
    path: '/anomaly',
    name: 'Anomaly',
    component: () => import('@/views/Anomaly.vue'),
  },
  {
    path: '/packets',
    name: 'PacketLog',
    component: () => import('@/views/PacketLog.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
