<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from '@/plugins/element-plus'
import {
  cleanupOldLogs,
  fetchAllLoginLogs,
  fetchAuditLogs,
  fetchLogSummary,
  type AuditLogItem,
  type LoginAuditLogItem,
  type LogSummary,
} from '@/api/logs'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('log:audit:manage'))

const activeTab = ref<'audit' | 'login'>('audit')
const summary = ref<LogSummary>({
  audit_total_24h: 0,
  audit_alert_24h: 0,
  login_success_24h: 0,
  login_failed_24h: 0,
  by_module: {},
})

// 操作审计日志查询
const auditLoading = ref(false)
const auditRows = ref<AuditLogItem[]>([])
const auditTotal = ref(0)
const auditQuery = reactive({
  page: 1,
  page_size: 15,
  keyword: '',
  module: '',
  result: '',
  method: '',
})

// 登录审计日志查询
const loginLoading = ref(false)
const loginRows = ref<LoginAuditLogItem[]>([])
const loginTotal = ref(0)
const loginQuery = reactive({
  page: 1,
  page_size: 15,
  keyword: '',
  status: '',
})

// 详情弹窗
const detailVisible = ref(false)
const detailItem = ref<AuditLogItem | null>(null)
const cleaning = ref(false)

const moduleOptions = [
  { label: '账号与分配 (account)', value: 'account' },
  { label: '认证与注册 (auth)', value: 'auth' },
  { label: '多端会话 (session)', value: 'session' },
  { label: 'AI 模型中心 (ai)', value: 'ai' },
  { label: '系统配置 (system)', value: 'system' },
  { label: 'RBAC 权限 (rbac)', value: 'rbac' },
  { label: '日志审计 (log)', value: 'log' },
  { label: '小程序用户 (miniapp_user)', value: 'miniapp_user' },
]

async function loadSummary() {
  summary.value = await fetchLogSummary()
}

async function loadAuditLogs() {
  auditLoading.value = true
  try {
    const res = await fetchAuditLogs(auditQuery)
    auditRows.value = res.items
    auditTotal.value = res.total
  } finally {
    auditLoading.value = false
  }
}

async function loadLoginLogs() {
  loginLoading.value = true
  try {
    const res = await fetchAllLoginLogs(loginQuery)
    loginRows.value = res.items
    loginTotal.value = res.total
  } finally {
    loginLoading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadSummary(), loadAuditLogs(), loadLoginLogs()])
}

function searchAudit() {
  auditQuery.page = 1
  void loadAuditLogs()
}

function resetAudit() {
  auditQuery.keyword = ''
  auditQuery.module = ''
  auditQuery.result = ''
  auditQuery.method = ''
  auditQuery.page = 1
  void loadAuditLogs()
}

function searchLogin() {
  loginQuery.page = 1
  void loadLoginLogs()
}

function resetLogin() {
  loginQuery.keyword = ''
  loginQuery.status = ''
  loginQuery.page = 1
  void loadLoginLogs()
}

function openDetail(row: AuditLogItem) {
  detailItem.value = row
  detailVisible.value = true
}

function formattedSummary(raw: string): string {
  if (!raw) return '无请求体或已跳过采集'
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

async function handleCleanup() {
  try {
    await ElMessageBox.confirm(
      '将依据「系统配置 → 日志留存策略」设定的保留天数，清理过期操作审计与登录安全日志，是否继续？',
      '清理过期日志确认',
      { confirmButtonText: '确认清理', cancelButtonText: '取消', type: 'warning' },
    )
    cleaning.value = true
    const res = await cleanupOldLogs({ target: 'all' })
    ElMessage.success(
      `清理完成（保留近 ${res.retention_days} 天）：移除操作日志 ${res.deleted_audit_logs} 条、登录日志 ${res.deleted_login_logs} 条`,
    )
    await refreshAll()
  } catch {
    // 取消
  } finally {
    cleaning.value = false
  }
}

onMounted(() => {
  void refreshAll()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">操作审计与安全日志中心</h2>
        <p class="page-subtitle">
          全链路追踪后台写操作、403 越权拦截、5xx 异常与全站登录安全事件；敏感字段自动脱敏落库
        </p>
      </div>
      <div class="header-actions">
        <el-button icon="Refresh" @click="refreshAll">刷新数据</el-button>
        <el-button
          v-if="canManage"
          type="danger"
          plain
          icon="Delete"
          :loading="cleaning"
          @click="handleCleanup"
        >
          清理过期日志
        </el-button>
      </div>
    </div>

    <!-- 24 小时 KPI 概览 -->
    <el-row :gutter="16" class="kpi-row">
      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card">
          <span class="kpi-label">24h 操作审计总数</span>
          <div class="kpi-val mono-num">{{ summary.audit_total_24h }}</div>
          <span class="kpi-foot">含管理变更与状态写操作</span>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card is-alert">
          <span class="kpi-label">24h 异常与越权拦截</span>
          <div class="kpi-val mono-num">{{ summary.audit_alert_24h }}</div>
          <span class="kpi-foot">403 权限拒绝 / 请求异常</span>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card">
          <span class="kpi-label">24h 登录成功次数</span>
          <div class="kpi-val mono-num is-ok">{{ summary.login_success_24h }}</div>
          <span class="kpi-foot">全站多端认证通过记录</span>
        </div>
      </el-col>
      <el-col :xs="24" :sm="12" :lg="6">
        <div class="kpi-card">
          <span class="kpi-label">24h 登录失败拦截</span>
          <div class="kpi-val mono-num is-warn">{{ summary.login_failed_24h }}</div>
          <span class="kpi-foot">含密码错误与防爆破锁定</span>
        </div>
      </el-col>
    </el-row>

    <div class="page-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="系统操作审计日志" name="audit">
          <el-form :inline="true" :model="auditQuery" class="search-bar">
            <el-form-item label="关键字">
              <el-input
                v-model="auditQuery.keyword"
                placeholder="操作人 / 路径 / 动作 / RequestID"
                clearable
                style="width: 230px"
                @keyup.enter="searchAudit"
              />
            </el-form-item>
            <el-form-item label="业务模块">
              <el-select v-model="auditQuery.module" placeholder="全部模块" clearable style="width: 175px">
                <el-option
                  v-for="m in moduleOptions"
                  :key="m.value"
                  :label="m.label"
                  :value="m.value"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="结果">
              <el-select v-model="auditQuery.result" placeholder="全部结果" clearable style="width: 120px">
                <el-option label="成功" value="success" />
                <el-option label="越权拦截" value="denied" />
                <el-option label="失败异常" value="error" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="searchAudit">筛选</el-button>
              <el-button @click="resetAudit">重置</el-button>
            </el-form-item>
          </el-form>

          <el-table v-loading="auditLoading" :data="auditRows" stripe border>
            <el-table-column prop="created_at" label="时间" width="175">
              <template #default="{ row }">
                <span class="mono-num">{{ row.created_at || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作人 / 角色" min-width="175">
              <template #default="{ row }">
                <div class="op-cell">
                  <strong>{{ row.username }}</strong>
                  <span class="sub-tag mono-num">{{ row.role }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="模块与动作" min-width="185">
              <template #default="{ row }">
                <div class="op-cell">
                  <span>{{ row.action }}</span>
                  <span class="sub-tag mono-num">{{ row.module }} · {{ row.method }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="path" label="接口路径" min-width="205" show-overflow-tooltip>
              <template #default="{ row }">
                <code class="mono-num">{{ row.path }}</code>
              </template>
            </el-table-column>
            <el-table-column label="状态与耗时" width="145">
              <template #default="{ row }">
                <div class="status-cell mono-num">
                  <el-tag
                    size="small"
                    :type="
                      row.result === 'success'
                        ? 'success'
                        : row.result === 'denied'
                          ? 'warning'
                          : 'danger'
                    "
                  >
                    {{ row.status_code }}
                  </el-tag>
                  <span>{{ row.duration_ms }}ms</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="ip" label="来源 IP" width="130">
              <template #default="{ row }">
                <span class="mono-num">{{ row.ip || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="详情" width="85" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="openDetail(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="auditQuery.page"
              v-model:page-size="auditQuery.page_size"
              :total="auditTotal"
              layout="total, sizes, prev, pager, next"
              :page-sizes="[15, 30, 50]"
              @current-change="loadAuditLogs"
              @size-change="loadAuditLogs"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="全站登录安全日志" name="login">
          <el-form :inline="true" :model="loginQuery" class="search-bar">
            <el-form-item label="关键字">
              <el-input
                v-model="loginQuery.keyword"
                placeholder="账号 / 邮箱 / 客户端 IP"
                clearable
                style="width: 220px"
                @keyup.enter="searchLogin"
              />
            </el-form-item>
            <el-form-item label="登录结果">
              <el-select v-model="loginQuery.status" placeholder="全部" clearable style="width: 120px">
                <el-option label="成功" value="success" />
                <el-option label="失败" value="failed" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="searchLogin">筛选</el-button>
              <el-button @click="resetLogin">重置</el-button>
            </el-form-item>
          </el-form>

          <el-table v-loading="loginLoading" :data="loginRows" stripe border>
            <el-table-column prop="created_at" label="时间" width="180">
              <template #default="{ row }">
                <span class="mono-num">{{ row.created_at || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="account" label="登录账号/邮箱" min-width="200" />
            <el-table-column prop="ip" label="IP 地址" width="140">
              <template #default="{ row }">
                <span class="mono-num">{{ row.ip || '-' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="device_label" label="终端环境" min-width="160" />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.status === 'success' ? '成功' : '拦截/失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="fail_reason" label="失败或风控原因" min-width="200">
              <template #default="{ row }">{{ row.fail_reason || '-' }}</template>
            </el-table-column>
          </el-table>

          <div class="pagination-wrap">
            <el-pagination
              v-model:current-page="loginQuery.page"
              v-model:page-size="loginQuery.page_size"
              :total="loginTotal"
              layout="total, sizes, prev, pager, next"
              :page-sizes="[15, 30, 50]"
              @current-change="loadLoginLogs"
              @size-change="loadLoginLogs"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="detailVisible" title="审计日志链路详情" width="600px" destroy-on-close>
      <template v-if="detailItem">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="Request ID">
            <code class="mono-num">{{ detailItem.request_id }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="状态码 / 耗时">
            <span class="mono-num">{{ detailItem.status_code }} · {{ detailItem.duration_ms }}ms</span>
          </el-descriptions-item>
          <el-descriptions-item label="操作人">
            {{ detailItem.username }} ({{ detailItem.role }})
          </el-descriptions-item>
          <el-descriptions-item label="终端 / IP">
            {{ detailItem.device_label }} · {{ detailItem.ip || '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="操作语义" :span="2">
            {{ detailItem.action }} ({{ detailItem.method }} {{ detailItem.path }})
          </el-descriptions-item>
          <el-descriptions-item v-if="detailItem.error_message" label="异常/拦截说明" :span="2">
            <span style="color: var(--el-color-danger)">{{ detailItem.error_message }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <div class="summary-block">
          <div class="summary-label">脱敏请求参数摘要（敏感键已自动掩码）</div>
          <pre class="summary-pre mono-num">{{ formattedSummary(detailItem.request_summary) }}</pre>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  gap: 10px;
}

.kpi-row {
  margin-bottom: 18px;
}

.kpi-card {
  background: var(--ailove-surface);
  border: 1px solid var(--ailove-border);
  border-radius: 14px;
  box-shadow: var(--ailove-shadow-card);
  padding: 18px 20px;
  margin-bottom: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.kpi-card.is-alert {
  border-color: var(--ailove-brand-200);
}

.kpi-label {
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
}

.kpi-val {
  font-size: 28px;
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.kpi-val.is-ok {
  color: var(--ailove-success);
}

.kpi-val.is-warn {
  color: var(--ailove-warning);
}

.kpi-foot {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.search-bar {
  margin-bottom: 14px;
}

.op-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sub-tag {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.status-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.summary-block {
  margin-top: 16px;
}

.summary-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ailove-ink-secondary);
  margin-bottom: 6px;
}

.summary-pre {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
