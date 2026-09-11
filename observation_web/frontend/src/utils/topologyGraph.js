export const topologyStateLabels = {
  collected: '已采集', uncollected: '未采集', stale: '数据过期', unresolved: '待核实',
  observed: '已发现', conflict: '关系冲突', down: '端口断开', up: '端口已连接', unknown: '未知',
  manual: '人工确认',
}

const colors = { observed: '#438f78', manual: '#6378b8', down: '#d45656', stale: '#999fa9', unresolved: '#b88635', conflict: '#c65793' }
const endpointId = (device, port) => JSON.stringify([device, port])

export function topologyGraphOption(graph, expanded = new Set()) {
  const nodes = [], edges = [], known = new Set()
  const addNode = node => { if (!known.has(node.id)) { nodes.push(node); known.add(node.id) } }
  for (const device of graph.devices) {
    addNode({ id: device.id, name: device.name, deviceId: device.id, symbol: 'roundRect',
      symbolSize: [120, 46], itemStyle: { color: device.kind === 'switch' ? '#304e6e' : device.kind === 'external' ? '#8e8068' : '#437e83', opacity: device.stale ? 0.65 : 1 },
      label: { position: 'inside', color: '#fff', width: 110, overflow: 'truncate' } })
    if (!expanded.has(device.id)) continue
    for (const port of device.ports) {
      const location = port.location || '位置未知'
      const groupId = endpointId(device.id, 'group:' + location)
      if (!known.has(groupId)) {
        addNode({ id: groupId, name: location, deviceId: device.id, symbol: 'roundRect', symbolSize: [95, 30],
          itemStyle: { color: '#edf2f7', borderColor: '#adbccc', borderWidth: 1 }, label: { color: '#44566b', position: 'inside', width: 90, overflow: 'truncate' } })
        edges.push({ source: device.id, target: groupId, lineStyle: { type: 'dotted', color: '#c0c7d0' } })
      }
      const id = endpointId(device.id, port.id)
      addNode({ id, name: port.label, deviceId: device.id, portId: port.id, symbolSize: 13,
        itemStyle: { color: device.stale ? colors.stale : port.state === 'down' ? colors.down : '#579d87' } })
      edges.push({ source: groupId, target: id, lineStyle: { type: 'dotted', color: '#c0c7d0' } })
    }
  }
  const resolveEnd = (device, port) => {
    if (!expanded.has(device)) return device
    const id = endpointId(device, port)
    addNode({ id, name: port.replace(/^unresolved:/, ''), deviceId: device, portId: port,
      symbolSize: 13, itemStyle: { color: colors.unresolved } })
    return id
  }
  const pairCount = new Map()
  for (const link of graph.links) {
    const pair = JSON.stringify([link.source, link.target].sort())
    const index = pairCount.get(pair) || 0
    pairCount.set(pair, index + 1)
    edges.push({ source: resolveEnd(link.source, link.source_port), target: resolveEnd(link.target, link.target_port),
      linkId: link.id, name: `${link.source_port} ↔ ${link.target_port}`,
      lineStyle: { color: colors[link.state] || colors.unresolved, width: 2,
        type: ['stale', 'unresolved'].includes(link.state) ? 'dashed' : 'solid', curveness: 0.12 + index * 0.12 } })
  }
  return { animation: false, series: [{ type: 'graph', layout: 'force', roam: true,
    draggable: true, data: nodes, links: edges, force: { repulsion: 330, edgeLength: [95, 160], gravity: 0.06 },
    label: { show: true, position: 'bottom', fontSize: 12, color: '#354052', width: 130, overflow: 'truncate' },
    emphasis: { focus: 'adjacency', lineStyle: { width: 4 } }, scaleLimit: { min: 0.2, max: 4 } }] }
}
