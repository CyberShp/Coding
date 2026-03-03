import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('../views/Dashboard.vue'),
  },
  {
    path: '/arrays',
    name: 'Arrays',
    component: () => import('../views/Arrays.vue'),
  },
  {
    path: '/arrays/tag/:tagId',
    name: 'TagArrays',
    component: () => import('../views/TagArrays.vue'),
  },
  {
    path: '/arrays/:id',
    name: 'ArrayDetail',
    component: () => import('../views/ArrayDetail.vue'),
  },
  {
    path: '/alerts',
    name: 'Alerts',
    component: () => import('../views/AlertCenter.vue'),
  },
  {
    path: '/query',
    name: 'Query',
    component: () => import('../views/CustomQuery.vue'),
  },
  {
    path: '/admin/login',
    name: 'AdminLogin',
    component: () => import('../views/AdminLogin.vue'),
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
  },
  {
    path: '/system-alerts',
    name: 'SystemAlerts',
    component: () => import('../views/SystemAlerts.vue'),
  },
  {
    path: '/data',
    name: 'DataManagement',
    component: () => import('../views/DataManagement.vue'),
  },
  {
    path: '/tasks',
    name: 'ScheduledTasks',
    component: () => import('../views/ScheduledTasks.vue'),
  },
  {
    path: '/test-tasks',
    name: 'TestTasks',
    component: () => import('../views/TestTasks.vue'),
  },
  {
    path: '/issues',
    name: 'Issues',
    component: () => import('../views/Issues.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
