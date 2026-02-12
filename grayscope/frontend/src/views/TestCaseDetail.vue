<template>
  <div class="gs-page gs-tc-detail-page">
    <!-- 返回导航 -->
    <div class="gs-tc-nav gs-section">
      <router-link to="/test-design" class="gs-back-link">&larr; 返回测试设计中心</router-link>
    </div>

    <!-- 加载/错误状态 -->
    <div v-if="!tc" class="gs-tc-empty">
      <el-empty description="未找到测试用例数据，请从测试设计中心进入">
        <router-link to="/test-design"><el-button type="primary">前往测试设计中心</el-button></router-link>
      </el-empty>
    </div>

    <template v-else>
      <!-- 头部卡片 -->
      <div class="gs-tc-hero gs-section">
        <div class="gs-tc-hero-top">
          <span class="gs-tc-prio-badge" :class="prioClass">{{ prioLabel }}</span>
          <code class="gs-tc-id-label">{{ tc.test_case_id }}</code>
          <span class="gs-tc-module-badge">{{ tc.module_display_name }}</span>
          <span v-if="projectName" class="gs-tc-project-badge">{{ projectName }}</span>
          <div style="flex:1"></div>
          <span class="gs-tc-risk-badge" :style="{ background: riskBg }">
            风险 {{ (tc.risk_score * 100).toFixed(0) }}%
          </span>
        </div>
        <h1 class="gs-tc-hero-title">{{ tc.title || '未命名测试用例' }}</h1>
        <p class="gs-tc-hero-objective">
          <el-icon><Aim /></el-icon>
          {{ tc.objective }}
        </p>
        <div class="gs-tc-hero-location">
          <el-icon><Document /></el-icon>
          <code>{{ tc.target_file }}</code>
          <span v-if="tc.target_function"> → <code>{{ tc.target_function }}()</code></span>
          <span v-if="tc.line_start" class="gs-tc-hero-lines">L{{ tc.line_start }}<span v-if="tc.line_end">–{{ tc.line_end }}</span></span>
        </div>
      </div>

      <!-- 两栏：左=测试设计，右=分析证据 -->
      <div class="gs-tc-body">
        <!-- 左栏：完整测试设计 -->
        <div class="gs-tc-col-left">
          <div class="gs-tc-card">
            <h2 class="gs-tc-card-title"><el-icon><List /></el-icon> 前置条件</h2>
            <ul class="gs-tc-list" v-if="tc.preconditions?.length">
              <li v-for="(p, i) in tc.preconditions" :key="i">{{ p }}</li>
            </ul>
            <p v-else class="gs-tc-muted">无特殊前置条件</p>
          </div>

          <div class="gs-tc-card">
            <h2 class="gs-tc-card-title"><el-icon><Guide /></el-icon> 测试步骤</h2>
            <ol class="gs-tc-steps" v-if="tc.test_steps?.length">
              <li v-for="(s, i) in tc.test_steps" :key="i">
                <span class="gs-tc-step-text">{{ stripNumber(s) }}</span>
              </li>
            </ol>
            <p v-else class="gs-tc-muted">无测试步骤</p>
          </div>

          <div class="gs-tc-card gs-tc-card-expected">
            <h2 class="gs-tc-card-title"><el-icon><CircleCheck /></el-icon> 预期结果</h2>
            <div class="gs-tc-expected-body">{{ tc.expected_result }}</div>
          </div>

          <!-- 风险类型信息 -->
          <div class="gs-tc-card" v-if="tc.category">
            <h2 class="gs-tc-card-title"><el-icon><WarningFilled /></el-icon> 风险分类</h2>
            <div class="gs-tc-risk-info">
              <el-tag size="default">{{ tc.category }}</el-tag>
              <span class="gs-tc-risk-desc">{{ riskDescription }}</span>
            </div>
          </div>
        </div>

        <!-- 右栏：分析证据 -->
        <div class="gs-tc-col-right">
          <div class="gs-tc-card" v-if="tc.evidence && Object.keys(tc.evidence).length">
            <h2 class="gs-tc-card-title"><el-icon><DataAnalysis /></el-icon> 分析证据</h2>
            <div class="gs-tc-evidence-full">
              <EvidenceRenderer
                :module-id="tc.module_id"
                :risk-type="tc.category"
                :evidence="tc.evidence"
                :finding="tc"
              />
            </div>
          </div>
          <div class="gs-tc-card" v-else>
            <h2 class="gs-tc-card-title"><el-icon><DataAnalysis /></el-icon> 分析证据</h2>
            <p class="gs-tc-muted">此用例无关联的结构化证据</p>
          </div>

          <!-- 来源发现信息 -->
          <div class="gs-tc-card" v-if="tc.source_finding_id">
            <h2 class="gs-tc-card-title"><el-icon><Connection /></el-icon> 来源发现</h2>
            <div class="gs-tc-source">
              <code>{{ tc.source_finding_id }}</code>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Aim, Document, List, Guide, CircleCheck, WarningFilled, DataAnalysis, Connection } from '@element-plus/icons-vue'
import { useAppStore } from '../stores/app.js'
import { useRiskColor } from '../composables/useRiskColor.js'
import EvidenceRenderer from '../components/EvidenceRenderer.vue'

const route = useRoute()
const appStore = useAppStore()
const { riskColor } = useRiskColor()

const tc = ref(null)

onMounted(() => {
  // 从路由状态获取测试用例数据
  if (history.state?.tc) {
    tc.value = history.state.tc
  }
  appStore.fetchProjects()
})

const projectName = computed(() => {
  if (!tc.value?.project_id) return ''
  const p = appStore.getProjectById(tc.value.project_id)
  return p?.name || `项目#${tc.value.project_id}`
})

const prioLabel = computed(() => {
  if (!tc.value?.priority) return 'P3'
  return tc.value.priority.split('-')[0]
})

const prioClass = computed(() => {
  return `prio-${prioLabel.value.toLowerCase()}`
})

const riskBg = computed(() => {
  if (!tc.value) return '#999'
  return riskColor(tc.value.risk_score)
})

const riskDescription = computed(() => {
  const map = {
    boundary_miss: '约束条件缺少边界值检查',
    invalid_input_gap: '输入校验不完整，可能导致越界',
    branch_error: '错误处理分支可能未正确触发',
    branch_cleanup: '清理路径可能遗漏资源释放',
    branch_boundary: '边界条件分支处理可能不完整',
    missing_cleanup: '错误路径上可能未释放资源',
    changed_core_path: '变更影响了核心调用路径',
    transitive_impact: '变更通过传递依赖影响下游函数',
    deep_impact_surface: '变更的影响面较深',
    race_write_without_lock: '共享变量写入缺少锁保护',
    deep_param_propagation: '参数通过多层调用链传播',
    external_to_sensitive: '外部输入传播到敏感操作',
    value_transform_risk: '值在传播过程中经历变换',
  }
  return map[tc.value?.category] || '详见分析证据'
})

function stripNumber(s) {
  return s.replace(/^\d+\.\s*/, '')
}
</script>

<style scoped>
.gs-tc-detail-page { max-width: 1200px; margin: 0 auto; }

.gs-tc-nav { margin-bottom: 8px; }
.gs-back-link {
  font-size: 13px; color: var(--gs-primary); text-decoration: none;
  display: inline-flex; align-items: center; gap: 4px;
}
.gs-back-link:hover { text-decoration: underline; }

/* ── 头部 ── */
.gs-tc-hero {
  background: var(--gs-surface); border: 1px solid var(--gs-border);
  border-radius: var(--gs-radius-md); padding: 24px 28px;
  margin-bottom: 16px;
}
.gs-tc-hero-top {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;
}
.gs-tc-prio-badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 36px; height: 26px; padding: 0 10px;
  border-radius: 6px; font-size: 12px; font-weight: 700; color: #fff;
}
.gs-tc-prio-badge.prio-p0 { background: var(--gs-risk-critical); }
.gs-tc-prio-badge.prio-p1 { background: var(--gs-risk-high); }
.gs-tc-prio-badge.prio-p2 { background: var(--gs-risk-medium); }
.gs-tc-prio-badge.prio-p3 { background: var(--gs-risk-low); }

.gs-tc-id-label {
  font-size: 12px; font-family: var(--gs-font-mono); color: var(--gs-text-muted);
  background: var(--gs-bg); padding: 2px 8px; border-radius: 4px;
}
.gs-tc-module-badge {
  font-size: 11px; padding: 3px 10px;
  background: rgba(75, 159, 213, 0.1); color: var(--gs-primary); border-radius: 12px;
}
.gs-tc-project-badge {
  font-size: 11px; padding: 3px 10px;
  background: rgba(0, 170, 0, 0.08); color: var(--gs-success); border-radius: 12px;
}
.gs-tc-risk-badge {
  padding: 4px 14px; border-radius: 12px;
  font-size: 12px; font-weight: 600; color: #fff;
}
.gs-tc-hero-title {
  font-size: 20px; font-weight: 700; color: var(--gs-text-primary);
  margin: 0 0 10px 0; line-height: 1.4;
}
.gs-tc-hero-objective {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: 14px; color: var(--gs-text-secondary); line-height: 1.6; margin: 0 0 12px 0;
}
.gs-tc-hero-objective .el-icon { margin-top: 3px; color: var(--gs-primary); flex-shrink: 0; }
.gs-tc-hero-location {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; color: var(--gs-text-muted);
}
.gs-tc-hero-location .el-icon { color: var(--gs-text-muted); }
.gs-tc-hero-location code {
  background: rgba(75, 159, 213, 0.08); padding: 2px 8px; border-radius: 4px;
  font-size: 12px; font-family: var(--gs-font-mono);
}
.gs-tc-hero-lines { margin-left: 6px; font-family: var(--gs-font-mono); font-size: 12px; }

/* ── 两栏布局 ── */
.gs-tc-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  align-items: start;
}
@media (max-width: 900px) {
  .gs-tc-body { grid-template-columns: 1fr; }
}

.gs-tc-card {
  background: var(--gs-surface); border: 1px solid var(--gs-border);
  border-radius: var(--gs-radius-md); padding: 20px 24px;
  margin-bottom: 12px;
  overflow: hidden;
  min-width: 0;
}
.gs-tc-card-title {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: var(--gs-text-primary);
  margin: 0 0 14px 0;
}
.gs-tc-card-title .el-icon { color: var(--gs-primary); }

/* ── 列表 ── */
.gs-tc-list, .gs-tc-steps {
  margin: 0; padding-left: 22px;
  font-size: 13px; color: var(--gs-text-secondary); line-height: 2;
}
.gs-tc-steps li::marker { color: var(--gs-primary); font-weight: 600; }
.gs-tc-step-text { display: inline; }
.gs-tc-muted { font-size: 13px; color: var(--gs-text-muted); margin: 0; }

/* ── 预期结果 ── */
.gs-tc-card-expected { border-left: 3px solid var(--gs-success); }
.gs-tc-expected-body {
  font-size: 14px; color: var(--gs-success); font-weight: 500;
  line-height: 1.7; padding: 12px 16px;
  background: rgba(0, 170, 0, 0.05); border-radius: var(--gs-radius-sm);
}

/* ── 风险分类 ── */
.gs-tc-risk-info { display: flex; align-items: center; gap: 12px; }
.gs-tc-risk-desc { font-size: 13px; color: var(--gs-text-secondary); }

/* ── 证据区域（全宽展示） ── */
.gs-tc-evidence-full {
  background: var(--gs-bg); border-radius: var(--gs-radius-sm); padding: 16px;
  overflow: hidden;
  min-width: 0;
}

/* ── 来源发现 ── */
.gs-tc-source code {
  font-size: 12px; background: var(--gs-bg); padding: 4px 10px; border-radius: 4px;
  font-family: var(--gs-font-mono);
}

.gs-tc-empty { padding: 80px 0; text-align: center; }
</style>
