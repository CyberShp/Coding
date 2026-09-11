import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import authEvents, { AUTH_LOGIN_REQUIRED } from '../utils/authEvents'

// Guard for pages that any logged-in user may use (multi-user Phase 2).
// Anonymous users get the LoginDialog popped (via the global auth event bus)
// instead of being redirected to the legacy admin-login page; navigation is
// aborted so they stay where they are until they log in.
function requireLogin(to) {
  const auth = useAuthStore()
  if (!auth.isLoggedIn) {
    authEvents.emit(AUTH_LOGIN_REQUIRED, { url: to.fullPath })
    return false
  }
}

const routes = [
  { path: '/topology', name: 'Topology', component: () => import('../views/Topology.vue') },
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
    path: '/admin/monitors',
    name: 'AdminMonitors',
    component: () => import('../views/AdminMonitors.vue'),
    beforeEnter: requireLogin,
  },
  {
    path: '/monitor-health',
    name: 'MonitorHealth',
    component: () => import('../views/MonitorHealth.vue'),
    beforeEnter: requireLogin,
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
  {
    path: '/card-inventory',
    name: 'CardInventory',
    component: () => import('../views/CardInventory.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
