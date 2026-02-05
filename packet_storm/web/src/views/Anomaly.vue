<template>
  <div class="anomaly-page">
    <h2 class="page-title">Anomaly Types</h2>

    <!-- Filter -->
    <el-card class="filter-card" shadow="never">
      <el-space :size="12">
        <el-select v-model="selectedCategory" placeholder="Category" clearable>
          <el-option label="All" value="" />
          <el-option label="Generic" value="generic" />
          <el-option label="iSCSI" value="iscsi" />
          <el-option label="NVMe-oF" value="nvmeof" />
          <el-option label="NAS" value="nas" />
        </el-select>
        <el-input v-model="searchText" placeholder="Search anomalies..." clearable style="width: 300px;" />
      </el-space>
    </el-card>

    <!-- Anomaly Table -->
    <el-card class="table-card" shadow="never" style="margin-top: 16px;">
      <el-table :data="filteredAnomalies" stripe size="default" style="width: 100%;">
        <el-table-column prop="name" label="Name" width="200">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.name }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="Category" width="120">
          <template #default="{ row }">
            <el-tag :type="categoryType(row.category)" size="small">
              {{ row.category }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="Description" />
        <el-table-column prop="applies_to" label="Applies To" width="150">
          <template #default="{ row }">
            {{ (row.applies_to || []).join(', ') }}
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Protocol Info -->
    <el-card class="proto-card" shadow="never" style="margin-top: 16px;">
      <template #header>
        <div class="card-header">
          <span>Protocol Packet Types</span>
          <el-select v-model="selectedProtocol" size="small" style="width: 150px;">
            <el-option label="iSCSI" value="iscsi" />
            <el-option label="NVMe-oF" value="nvmeof" />
            <el-option label="NAS" value="nas" />
          </el-select>
        </div>
      </template>
      <el-table :data="packetTypes" size="small" style="width: 100%;">
        <el-table-column prop="name" label="Packet Type" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import axios from 'axios'

const anomalies = ref([])
const packetTypes = ref([])
const selectedCategory = ref('')
const searchText = ref('')
const selectedProtocol = ref('iscsi')

const filteredAnomalies = computed(() => {
  let list = anomalies.value
  if (selectedCategory.value) {
    list = list.filter(a => a.category === selectedCategory.value)
  }
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    list = list.filter(a =>
      a.name.toLowerCase().includes(q) ||
      a.description.toLowerCase().includes(q)
    )
  }
  return list
})

function categoryType(cat) {
  if (cat === 'generic') return ''
  if (cat === 'iscsi') return 'warning'
  if (cat === 'nvmeof') return 'success'
  if (cat === 'nas') return 'danger'
  return 'info'
}

onMounted(async () => {
  try {
    const res = await axios.get('/api/anomaly/list')
    anomalies.value = res.data.anomalies || []
  } catch (e) {
    console.log('Could not load anomalies')
  }
  fetchPacketTypes()
})

watch(selectedProtocol, fetchPacketTypes)

async function fetchPacketTypes() {
  try {
    const res = await axios.get(`/api/anomaly/packet-types/${selectedProtocol.value}`)
    packetTypes.value = (res.data.packet_types || []).map(name => ({ name }))
  } catch (e) {
    packetTypes.value = []
  }
}
</script>

<style scoped>
.page-title { margin-bottom: 20px; color: #e0e0e0; }
.filter-card, .table-card, .proto-card { background: #16213e; border: 1px solid #2a2a3e; border-radius: 8px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
</style>
