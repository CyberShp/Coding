export const sections = [
  { id: 'overview', label: '总览', path: '/', pages: [] },
  { id: 'devices', label: '设备', path: '/arrays', pages: [
    { path: '/arrays', label: '存储设备' }, { path: '/topology', label: '以太网拓扑' },
    { path: '/card-inventory', label: '卡件列表' },
  ] },
  { id: 'alerts', label: '告警', path: '/alerts', pages: [
    { path: '/alerts', label: '设备告警' }, { path: '/system-alerts', label: '平台告警' },
  ] },
  { id: 'monitoring', label: '监测与测试', path: '/test-tasks', pages: [
    { path: '/test-tasks', label: '测试任务' }, { path: '/admin/monitors', label: '监测模板' },
    { path: '/monitor-health', label: '部署状态' }, { path: '/tasks', label: '定时任务' },
    { path: '/query', label: '查询工具' },
  ] },
  { id: 'settings', label: '设置', path: '/settings', pages: [
    { path: '/settings', label: '系统与个人设置' }, { path: '/data', label: '数据管理' },
  ] },
]

export function sectionForPath(path) {
  return sections.find(s => s.path === path || s.pages.some(p => path === p.path || path.startsWith(p.path + '/')))
}
