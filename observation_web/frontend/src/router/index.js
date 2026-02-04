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
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
