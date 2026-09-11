<template>
  <div class="topology-page">
    <div class="page-heading">
      <div><h2>以太网拓扑</h2><p>设备、卡件和端口之间的连接关系</p></div>
      <div class="actions">
        <el-button :disabled="managedDevices.filter(d => d.ports.length).length < 2" @click="cableVisible = true">人工确认接线</el-button>
        <el-button @click="switchesVisible = true">交换机管理</el-button>
        <el-button :loading="loading" @click="load()">刷新视图</el-button>
        <el-button type="primary" :loading="collecting" :disabled="!managedDevices.length" @click="collectAll">采集全部设备</el-button>
      </div>
    </div>
    <el-alert v-if="loadError" :title="loadError" type="error" :closable="false" show-icon />
    <el-alert v-if="collectionMessage" :title="collectionMessage" :type="collectionFailed ? 'warning' : 'info'" :closable="false" show-icon />
    <div class="topology-summary">
      <span>{{ managedDevices.length }} 台已添加设备</span><span>{{ graph.links.length }} 条发现的连接</span>
      <span>{{ managedDevices.filter(d => d.stale).length }} 台待采集或过期</span>
      <span class="muted">采集后 5 分钟标记过期</span>
    </div>
    <el-empty v-if="!loading && !graph.devices.length && !loadError" description="添加存储设备或交换机后，在这里采集拓扑">
      <el-button @click="$router.push('/arrays')">添加存储设备</el-button>
      <el-button type="primary" @click="openSwitch()">添加交换机</el-button>
    </el-empty>
    <div v-else class="topology-workspace" v-loading="loading">
      <section class="graph-panel" aria-label="设备拓扑图">
        <div class="graph-tools"><span>拖动节点 · 滚轮缩放 · 点击查看详情</span><el-button size="small" @click="expanded = new Set(); chartKey++">收起并重置</el-button></div>
        <v-chart :key="chartKey" :option="chartOption" autoresize class="topology-chart" @click="selectGraphItem" />
        <div class="legend"><span><i class="live"></i>发现的连接</span><span><i class="manual"></i>人工确认</span><span><i class="down"></i>端口断开</span><span><i class="conflict"></i>关系冲突</span><span><i class="aged"></i>过期 / 待核实</span><span><i class="membership"></i>设备归属</span></div>
      </section>
      <section class="details-panel" aria-live="polite">
        <template v-if="selectedLink">
          <div class="detail-heading"><h3>连接详情</h3><el-tag>{{ stateLabel(selectedLink.state) }}</el-tag></div>
          <p class="endpoint">{{ deviceName(selectedLink.source) }}<br><code>{{ displayPort(selectedLink.source_port) }}</code></p>
          <div class="connection-mark">↕</div>
          <p class="endpoint">{{ deviceName(selectedLink.target) }}<br><code>{{ displayPort(selectedLink.target_port) }}</code></p>
          <p class="muted">{{ { bilateral: '两端均有邻居证据', unilateral: '单端邻居证据', manual: '人工记录的物理接线' }[selectedLink.confirmation] }}</p>
          <el-button v-if="selectedLink.manual_id" size="small" @click="removeCable(selectedLink.manual_id)">撤销人工接线</el-button>
          <div v-for="(evidence, index) in selectedLink.evidence" :key="index" class="evidence">
            <strong>{{ deviceName(evidence.device_id) }} · {{ evidence.source }}</strong>
            <p>{{ formatTime(evidence.collected_at) }}</p>
            <p v-if="evidence.confirmed_by">确认人：{{ evidence.confirmed_by }}</p>
            <template v-else><p>邻居标识：{{ evidence.remote_chassis }}</p>
            <p>管理地址：{{ evidence.remote_address || '未提供' }}</p></template>
          </div>
        </template>
        <template v-else-if="selectedDevice">
          <div class="detail-heading"><h3>{{ selectedDevice.name }}</h3><el-tag>{{ stateLabel(selectedDevice.state) }}</el-tag></div>
          <p>{{ selectedDevice.host || '管理地址未知' }}</p>
          <p class="muted">上次成功：{{ formatTime(selectedDevice.collected_at) }}</p>
          <el-alert v-if="selectedDevice.last_error" :title="selectedDevice.last_error" type="warning" :closable="false" />
          <p v-if="selectedDevice.notice" class="notice">{{ selectedDevice.notice }}</p>
          <div class="actions detail-actions">
            <el-button v-if="selectedDevice.kind !== 'external'" size="small" :disabled="collecting" @click="collectOne(selectedDevice)">采集此设备</el-button>
            <el-button v-if="selectedDevice.ports.length" size="small" @click="toggleExpand(selectedDevice.id)">{{ expanded.has(selectedDevice.id) ? '收起端口' : '展开卡件与端口' }}</el-button>
            <el-button v-if="selectedDevice.array_id" size="small" @click="$router.push('/arrays/' + selectedDevice.array_id)">存储详情</el-button>
          </div>
          <el-empty v-if="!selectedDevice.ports.length" :image-size="45" description="尚无端口信息" />
          <div v-for="group in portGroups" :key="group.name" class="port-group">
            <h4>{{ group.name }}</h4>
            <button v-for="port in group.ports" :key="port.id" class="port-row" @click="selectPort(selectedDevice.id, port.id)">
              <span>{{ port.label }}<small>{{ portKind(port.kind) }} · {{ port.speed && port.speed !== '--' ? port.speed + ' Mbps' : '速率未知' }}</small></span>
              <span>{{ selectedDevice.stale ? '状态过期' : stateLabel(port.state) }}<small>{{ portConnections(selectedDevice.id, port.id) ? '查看连接' : '对端未知' }}</small></span>
            </button>
          </div>
        </template>
        <el-empty v-else :image-size="70" description="选择设备或连接，查看端口和采集证据" />
      </section>
    </div>
    <el-card v-if="graph.devices.length" class="inventory-panel" shadow="never">
      <template #header><span>全部设备</span></template>
      <el-table :data="graph.devices" @row-click="selectDevice">
        <el-table-column prop="name" label="设备" min-width="160" />
        <el-table-column label="类型" width="120"><template #default="{ row }">{{ { storage: '存储', switch: '交换机', external: '未匹配邻居' }[row.kind] }}</template></el-table-column>
        <el-table-column prop="host" label="管理地址" min-width="130" />
        <el-table-column label="采集状态" width="120"><template #default="{ row }">{{ stateLabel(row.state) }}</template></el-table-column>
        <el-table-column label="上次成功" min-width="170"><template #default="{ row }">{{ formatTime(row.collected_at) }}</template></el-table-column>
      </el-table>
    </el-card>
    <el-card v-if="graph.links.length" class="inventory-panel" shadow="never">
      <template #header><span>连接清单</span></template>
      <el-table :data="graph.links" @row-click="row => selectedLinkId = row.id">
        <el-table-column label="设备 A / 端口" min-width="200"><template #default="{ row }">{{ deviceName(row.source) }} / {{ displayPort(row.source_port) }}</template></el-table-column>
        <el-table-column label="设备 B / 端口" min-width="200"><template #default="{ row }">{{ deviceName(row.target) }} / {{ displayPort(row.target_port) }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }">{{ stateLabel(row.state) }}</template></el-table-column>
        <el-table-column label="来源" width="100"><template #default="{ row }">{{ row.confirmation === 'manual' ? '人工确认' : 'LLDP' }}</template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="{ row }"><el-button link type="primary" @click="selectedLinkId = row.id">查看详情</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="cableVisible" title="人工确认物理接线" width="min(520px, 95vw)">
      <el-alert title="按实际接线选择两端端口。此记录会标明人工来源，与自动采集的邻居证据分别保留。" type="info" :closable="false" />
      <el-form label-position="top">
        <template v-for="end in ['source', 'target']" :key="end">
          <el-form-item :label="end === 'source' ? '设备 A' : '设备 B'">
            <el-select v-model="cableForm[end]" @change="cableForm[end + '_port'] = ''">
              <el-option v-for="device in managedDevices.filter(d => d.ports.length)" :key="device.id" :label="device.name" :value="device.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="物理端口"><el-select v-model="cableForm[end + '_port']">
            <el-option v-for="port in graph.devices.find(d => d.id === cableForm[end])?.ports || []" :key="port.id" :label="port.label" :value="port.id" />
          </el-select></el-form-item>
        </template>
      </el-form>
      <template #footer><el-button @click="cableVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveCable">确认接线</el-button></template>
    </el-dialog>
    <el-dialog v-model="switchesVisible" title="交换机管理" width="min(800px, 95vw)">
      <el-button type="primary" @click="openSwitch()">添加交换机</el-button>
      <el-table :data="switches">
        <el-table-column prop="name" label="名称" /><el-table-column prop="host" label="SSH 地址" />
        <el-table-column label="操作" width="150"><template #default="{ row }"><el-button link type="primary" @click="openSwitch(row)">编辑</el-button><el-button link type="danger" :disabled="collecting" @click="removeSwitch(row)">删除</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
    <el-dialog v-model="editVisible" :title="editingId ? '编辑交换机' : '添加华为交换机'" width="min(480px, 95vw)">
      <el-form label-position="top" @submit.prevent="saveSwitch">
        <el-form-item label="名称"><el-input v-model="form.name" maxlength="128" /></el-form-item>
        <el-form-item label="SSH 地址"><el-input v-model="form.host" placeholder="IP 或主机名" maxlength="256" /></el-form-item>
        <el-form-item label="SSH 端口"><el-input-number v-model="form.port" :min="1" :max="65535" /></el-form-item>
        <el-form-item label="用户名"><el-input v-model="form.username" maxlength="64" /></el-form-item>
        <el-form-item :label="editingId ? '密码（留空保留已保存密码）' : '密码'"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" /></el-form-item>
        <el-form-item label="SSH 私钥路径（使用密钥时填写平台服务器上的路径）"><el-input v-model="form.key_path" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="editVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="saveSwitch">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { use } from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import api, { extractError } from '../api'
import { topologyGraphOption, topologyStateLabels } from '../utils/topologyGraph'

use([GraphChart, CanvasRenderer])
const graph = ref({ devices: [], links: [] })
const switches = ref([]), expanded = ref(new Set()), chartKey = ref(0)
const loading = ref(false), collecting = ref(false), saving = ref(false)
const loadError = ref(''), collectionMessage = ref(''), collectionFailed = ref(false)
const selectedDeviceId = ref(''), selectedLinkId = ref('')
const switchesVisible = ref(false), editVisible = ref(false), editingId = ref('')
const cableVisible = ref(false)
const cableForm = reactive({ source: '', source_port: '', target: '', target_port: '' })
const form = reactive({ name: '', host: '', port: 22, username: '', password: '', key_path: '' })
let active = true, refreshTimer
const managedDevices = computed(() => graph.value.devices.filter(d => d.kind !== 'external'))
const selectedDevice = computed(() => graph.value.devices.find(d => d.id === selectedDeviceId.value))
const selectedLink = computed(() => graph.value.links.find(l => l.id === selectedLinkId.value))
const chartOption = computed(() => topologyGraphOption(graph.value, expanded.value))
const portGroups = computed(() => {
  const groups = new Map()
  for (const port of selectedDevice.value?.ports || []) {
    const key = port.location || '位置未知'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(port)
  }
  return [...groups].map(([name, ports]) => ({ name, ports }))
})
const stateLabel = state => topologyStateLabels[state] || state
const formatTime = value => value ? new Date(value).toLocaleString() : '尚未采集'
const displayPort = value => value.replace(/^unresolved:/, '')
const deviceName = id => graph.value.devices.find(d => d.id === id)?.name || id
const portKind = kind => ({ card: '卡件端口', onboard: '板载口', ethernet: '以太网口', unknown: '位置待核实' }[kind] || '位置待核实')
const portConnections = (id, port) => graph.value.links.find(l => (l.source === id && l.source_port === port) || (l.target === id && l.target_port === port))
function selectDevice(device) { selectedDeviceId.value = device.id; selectedLinkId.value = '' }
function selectPort(id, port) { selectedLinkId.value = portConnections(id, port)?.id || '' }
function selectGraphItem(event) {
  if (event.data?.linkId) selectedLinkId.value = event.data.linkId
  else if (event.data?.deviceId) { selectedDeviceId.value = event.data.deviceId; selectedLinkId.value = '' }
}
function toggleExpand(id) { const next = new Set(expanded.value); next.has(id) ? next.delete(id) : next.add(id); expanded.value = next }
async function load(silent = false) {
  if (loading.value) return
  loading.value = !silent
  try {
    const [topology, inventory] = await Promise.all([api.getTopology(), api.getTopologySwitches()])
    if (!active) return
    graph.value = topology.data; switches.value = inventory.data; loadError.value = ''
  } catch (error) { if (active) loadError.value = extractError(error, '拓扑读取失败') }
  finally { loading.value = false }
}
async function collectDevices(devices) {
  if (collecting.value) return
  collecting.value = true; collectionFailed.value = false
  let failures = 0, completed = 0
  try {
    for (const device of devices) {
      if (!active) break
      collectionMessage.value = `正在采集 ${device.name}（${completed + 1}/${devices.length}）`
      try { const res = await api.collectTopologyDevice(device.id); if (!res.data.success) failures++ }
      catch (error) { failures++; ElMessage.error(`${device.name}：${extractError(error)}`) }
      completed++; await load(true)
    }
    collectionFailed.value = failures > 0
    collectionMessage.value = `采集结束：${completed - failures} 台成功，${failures} 台失败。失败设备保留上次结果。`
  } finally { collecting.value = false }
}
function collectAll() { return collectDevices([...managedDevices.value]) }
function collectOne(device) { return collectDevices([device]) }
function openSwitch(row) {
  editingId.value = row?.id || ''
  Object.assign(form, { name: row?.name || '', host: row?.host || '', port: row?.port || 22, username: row?.username || '', password: '', key_path: row?.key_path || '' })
  editVisible.value = true
}
async function saveSwitch() {
  if (![form.name, form.host, form.username].every(v => v.trim()) || !form.port) { ElMessage.warning('请填写名称、SSH 地址、端口和用户名'); return }
  saving.value = true
  try {
    const data = { ...form, password: editingId.value && !form.password ? null : form.password }
    if (editingId.value) await api.updateTopologySwitch(editingId.value, data)
    else await api.createTopologySwitch(data)
    form.password = ''; editVisible.value = false; await load(); ElMessage.success('交换机已保存')
  } catch (error) { ElMessage.error(extractError(error)) }
  finally { saving.value = false }
}
async function removeSwitch(row) {
  try {
    await ElMessageBox.confirm(`删除交换机“${row.name}”及其采集记录？`, '删除交换机', { type: 'warning' })
    await api.deleteTopologySwitch(row.id); await load()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(extractError(error)) }
}
async function saveCable() {
  if (Object.values(cableForm).some(v => !v) || cableForm.source === cableForm.target) { ElMessage.warning('请选择两台设备及两端端口'); return }
  saving.value = true
  try { await api.confirmTopologyCable({ ...cableForm }); cableVisible.value = false; await load(); ElMessage.success('人工接线已保存') }
  catch (error) { ElMessage.error(extractError(error)) }
  finally { saving.value = false }
}
async function removeCable(id) {
  try { await ElMessageBox.confirm('撤销这条人工接线记录？', '撤销人工接线'); await api.removeTopologyCable(id); selectedLinkId.value = ''; await load() }
  catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(extractError(error)) }
}
onMounted(() => { load(); refreshTimer = setInterval(() => { if (!collecting.value) load(true) }, 30000) })
onUnmounted(() => { active = false; clearInterval(refreshTimer) })
</script>

<style scoped>
.page-heading, .actions, .detail-heading, .graph-tools, .topology-summary, .legend { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.page-heading, .detail-heading, .graph-tools { justify-content: space-between; }
.page-heading { margin-bottom: 20px; } h2 { font-size: 22px; } h3 { font-size: 16px; overflow-wrap: anywhere; }
.page-heading p, .muted { color: #737b87; font-size: 13px; margin-top: 6px; }
.topology-summary { margin: 16px 0; font-size: 13px; color: #536173; }
.topology-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 16px; }
.graph-panel, .details-panel { background: white; border: 1px solid #dfe5ec; border-radius: 6px; min-width: 0; }
.graph-panel { background-color: #fbfcfe; background-image: radial-gradient(#dfe6ef 0.7px, transparent 0.7px); background-size: 18px 18px; }
.graph-tools { padding: 12px 16px; border-bottom: 1px solid #e6eaf0; background: white; color: #737b87; font-size: 12px; }
.topology-chart { height: 560px; width: 100%; }
.details-panel { padding: 18px; max-height: 650px; overflow-y: auto; }
.details-panel p { margin: 10px 0; overflow-wrap: anywhere; }
.legend { padding: 12px 16px; font-size: 12px; background: white; }.legend span { display: flex; align-items: center; gap: 6px; }
.legend i { display: inline-block; width: 24px; border-top: 2px solid #438f78; }.legend i.manual { border-color: #6378b8; }.legend i.aged { border-top: 2px dashed #999fa9; }.legend i.membership { border-top: 1px dotted #9eabbc; }
.legend i.down { border-color: #d45656; }.legend i.conflict { border-color: #c65793; }
.detail-actions { margin: 16px 0; }.notice { padding: 10px; background: #f4f7fa; font-size: 12px; color: #5c6878; }
.port-group { margin-top: 20px; }.port-group h4 { color: #637389; font-size: 12px; margin-bottom: 6px; }
.port-row { display: flex; justify-content: space-between; gap: 8px; width: 100%; border: 0; border-bottom: 1px solid #e9edf3; padding: 10px 0; background: white; cursor: pointer; text-align: left; color: #344355; font-size: 12px; overflow-wrap: anywhere; }
.port-row:hover { background: #f2f7fc; }.port-row small { display: block; color: #7d8794; margin-top: 4px; }.port-row span:last-child { flex-shrink: 0; text-align: right; }
.endpoint { background: #f2f6fa; padding: 12px; border-radius: 4px; }.endpoint code { font-size: 12px; }.connection-mark { text-align: center; color: #60838a; }
.evidence { border-top: 1px solid #e5eaf0; margin-top: 16px; padding-top: 12px; font-size: 12px; }.inventory-panel { margin-top: 16px; }
@media (max-width: 1050px) { .topology-workspace { grid-template-columns: 1fr; }.details-panel { max-height: none; }.topology-chart { height: 440px; } }
</style>
