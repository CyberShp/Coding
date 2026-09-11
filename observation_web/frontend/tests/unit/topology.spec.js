import { describe, it, expect } from 'vitest'
import { sections, sectionForPath } from '../../src/navigation'
import { topologyGraphOption } from '../../src/utils/topologyGraph'

describe('topology and navigation', () => {
  it('keeps every existing feature reachable in five sections', () => {
    expect(sections).toHaveLength(5)
    for (const path of ['/arrays', '/arrays/a', '/arrays/tag/1', '/topology', '/card-inventory']) expect(sectionForPath(path).id).toBe('devices')
    expect(sectionForPath('/system-alerts').id).toBe('alerts')
    for (const path of ['/query', '/tasks', '/test-tasks', '/monitor-health', '/admin/monitors']) expect(sectionForPath(path).id).toBe('monitoring')
    expect(sectionForPath('/data').id).toBe('settings')
  })
  const graph = {
    devices: [
      { id: 'a', name: 'Storage', kind: 'storage', ports: [{ id: 'p1', label: 'p1', location: 'IOM0', state: 'up' }, { id: 'p2', label: 'p2', location: 'IOM0', state: 'up' }] },
      { id: 'b', name: 'Switch', kind: 'switch', ports: [{ id: 'ge1', label: 'ge1', location: '1/0', state: 'up' }] },
    ],
    links: [{ id: 'cable', source: 'a', source_port: 'p1', target: 'b', target_port: 'ge1', state: 'observed' }],
  }
  it('expands device ownership while attaching cable to physical port', () => {
    const series = topologyGraphOption(graph, new Set(['a'])).series[0]
    const cable = series.links.find(e => e.linkId === 'cable')
    expect(cable.source).not.toBe('a')
    const node = series.data.find(n => n.id === cable.source)
    expect(node.portId).toBe('p1')
    expect(cable.target).toBe('b')
    expect(series.links.filter(l => !l.linkId)).toHaveLength(3)
    expect(new Set(series.data.map(n => n.id)).size).toBe(series.data.length)
  })
  it('keeps multiple physical cables as separate selectable edges when collapsed', () => {
    const copy = structuredClone(graph)
    copy.links.push({ ...copy.links[0], id: 'cable2', source_port: 'p2' })
    const edges = topologyGraphOption(copy).series[0].links
    expect(edges).toHaveLength(2)
    expect(edges[0].lineStyle.curveness).not.toBe(edges[1].lineStyle.curveness)
  })
})
