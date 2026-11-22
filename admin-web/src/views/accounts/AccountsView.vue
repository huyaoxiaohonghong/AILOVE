<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import {
  adminCreateAccount,
  fetchAccounts,
  kickAccountSessions,
  resetAccountPassword,
  updateAccountStatus,
  type AccountItem,
} from '@/api/accounts'
import { checkEmailPolicy, type EmailAnalysisResult } from '@/api/auth'

const loading = ref(false)
const tableData = ref<AccountItem[]>([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
  role: '',
  register_source: '',
  is_active: '' as boolean | '',
})

// 管理员分配用户弹窗
const createDialogVisible = ref(false)
const creating = ref(false)
const createFormRef = ref<FormInstance>()
const emailCheckLoading = ref(false)
const emailAnalysis = ref<EmailAnalysisResult | null>(null)

const createForm = reactive({
  email: '',
  nickname: '',
  username: '',
  password: '',
  role: 'user' as 'user' | 'admin',
  allow_non_mainstream_email: false,
})

const createRules: FormRules = {
  email: [{ required: true, message: '请输入用户邮箱', trigger: 'blur' }],
  nickname: [{ required: true, message: '请输入用户昵称', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入初始密码', trigger: 'blur' },
    { min: 8, message: '密码至少 8 位', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        if (value && (!/[A-Za-z]/.test(value) || !/\d/.test(value))) {
          callback(new Error('密码需同时包含字母和数字'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}

async function loadAccounts() {
  loading.value = true
  try {
    const res = await fetchAccounts(query)
    tableData.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  query.page = 1
  void loadAccounts()
}

function handleReset() {
  query.keyword = ''
  query.role = ''
  query.register_source = ''
  query.is_active = ''
  query.page = 1
  void loadAccounts()
}

function openCreateDialog() {
  createForm.email = ''
  createForm.nickname = ''
  createForm.username = ''
  createForm.password = ''
  createForm.role = 'user'
  createForm.allow_non_mainstream_email = false
  emailAnalysis.value = null
  createDialogVisible.value = true
}

function generateStrongPassword() {
  const letters = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz'
  const digits = '23456789'
  const all = letters + digits
  let out = ''
  out += letters[Math.floor(Math.random() * letters.length)]
  out += digits[Math.floor(Math.random() * digits.length)]
  for (let i = 0; i < 10; i++) {
    out += all[Math.floor(Math.random() * all.length)]
  }
  createForm.password = out
}

async function handleCheckCreateEmail() {
  const email = createForm.email.trim()
  if (!email || !email.includes('@')) {
    emailAnalysis.value = null
    return
  }
  emailCheckLoading.value = true
  try {
    emailAnalysis.value = await checkEmailPolicy(email)
  } finally {
    emailCheckLoading.value = false
  }
}

async function handleCreateSubmit() {
  const valid = await createFormRef.value?.validate().catch(() => false)
  if (!valid) return

  creating.value = true
  try {
    await adminCreateAccount({
      email: createForm.email.trim(),
      nickname: createForm.nickname.trim(),
      username: createForm.username.trim() || undefined,
      password: createForm.password,
      role: createForm.role,
      allow_non_mainstream_email: createForm.allow_non_mainstream_email,
    })
    ElMessage.success('已成功分配并创建用户账号')
    createDialogVisible.value = false
    await loadAccounts()
  } finally {
    creating.value = false
  }
}

async function handleToggleStatus(row: AccountItem) {
  const nextActive = !row.is_active
  await updateAccountStatus(row.id, nextActive)
  row.is_active = nextActive
  ElMessage.success(nextActive ? '已启用该账号' : '已禁用该账号')
}

async function handleResetPassword(row: AccountItem) {
  try {
    const { value } = await ElMessageBox.prompt(
      `为用户「${row.nickname} (${row.email})」设置新密码（至少 8 位且包含字母和数字）`,
      '重置密码',
      {
        confirmButtonText: '确认重置',
        cancelButtonText: '取消',
        inputPlaceholder: '请输入新密码',
        inputPattern: /^(?=.*[A-Za-z])(?=.*\d).{8,128}$/,
        inputErrorMessage: '密码至少 8 位且需同时包含字母和数字',
      },
    )
    await resetAccountPassword(row.id, value)
    ElMessage.success('密码重置成功，原在线设备已自动下线')
    await loadAccounts()
  } catch {
    // 取消操作
  }
}

async function handleKickUser(row: AccountItem) {
  try {
    await ElMessageBox.confirm(
      `确认强制下线「${row.nickname} (${row.email})」的在线设备？`,
      '强制下线确认',
      { confirmButtonText: '确认下线', cancelButtonText: '取消', type: 'warning' },
    )
    const res = await kickAccountSessions(row.id)
    ElMessage.success(`已强制下线 ${res.kicked_sessions} 台设备`)
    await loadAccounts()
  } catch {
    // 取消操作
  }
}

function roleLabel(role: string) {
  if (role === 'super_admin') return '超级管理员'
  if (role === 'admin') return '管理员'
  return '普通用户'
}

function sourceLabel(source: string) {
  if (source === 'email_register') return '邮箱注册'
  if (source === 'admin_assigned') return '管理员分配'
  return '系统初始化'
}

onMounted(() => {
  void loadAccounts()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">平台账号与用户分配</h2>
        <p class="page-subtitle">
          统一管理通过「正规邮箱自助注册」及「管理员直接分配」创建的平台账号与邮箱风控评分
        </p>
      </div>
      <el-button type="primary" icon="Plus" @click="openCreateDialog">分配新用户</el-button>
    </div>

    <div class="page-card">
      <el-form :inline="true" :model="query" class="search-bar">
        <el-form-item label="关键字">
          <el-input
            v-model="query.keyword"
            placeholder="邮箱 / 昵称 / 用户名"
            clearable
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="query.register_source" placeholder="全部来源" clearable style="width: 140px">
            <el-option label="邮箱注册" value="email_register" />
            <el-option label="管理员分配" value="admin_assigned" />
            <el-option label="系统初始化" value="system_bootstrap" />
          </el-select>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="query.role" placeholder="全部角色" clearable style="width: 130px">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
            <el-option label="超级管理员" value="super_admin" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table v-loading="loading" :data="tableData" stripe border>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="用户" min-width="150">
          <template #default="{ row }">
            <div class="user-cell">
              <strong>{{ row.nickname }}</strong>
              <span v-if="row.username" class="sub-text">@{{ row.username }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱地址" min-width="210" show-overflow-tooltip />
        <el-table-column label="邮箱识别 / 可信分" min-width="185">
          <template #default="{ row }">
            <div class="trust-cell">
              <div class="trust-top">
                <span class="provider-text">{{ row.email_provider || '未标注' }}</span>
                <span
                  class="mono-num trust-num"
                  :class="
                    row.email_trust_score >= 80
                      ? 'is-high'
                      : row.email_trust_score >= 60
                        ? 'is-mid'
                        : 'is-low'
                  "
                >
                  {{ row.email_trust_score }}分
                </span>
              </div>
              <div class="trust-bar">
                <div
                  class="trust-fill"
                  :class="
                    row.email_trust_score >= 80
                      ? 'is-high'
                      : row.email_trust_score >= 60
                        ? 'is-mid'
                        : 'is-low'
                  "
                  :style="{ width: `${Math.max(8, Math.min(100, row.email_trust_score))}%` }"
                />
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="账号来源" width="115">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="
                row.register_source === 'email_register'
                  ? 'primary'
                  : row.register_source === 'admin_assigned'
                    ? 'success'
                    : 'info'
              "
            >
              {{ sourceLabel(row.register_source) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.role === 'user' ? 'info' : 'warning'"
              effect="light"
            >
              {{ roleLabel(row.role) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="在线设备" width="95">
          <template #default="{ row }">
            <el-tag :type="row.online_sessions > 0 ? 'success' : 'info'" size="small" effect="plain">
              {{ row.online_sessions ?? 0 }} 端
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="85">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
              {{ row.is_active ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_login_at" label="最近登录" width="175">
          <template #default="{ row }">{{ row.last_login_at || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="215" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.role !== 'super_admin'"
              link
              :type="row.is_active ? 'danger' : 'success'"
              @click="handleToggleStatus(row)"
            >
              {{ row.is_active ? '禁用' : '启用' }}
            </el-button>
            <el-button link type="primary" @click="handleResetPassword(row)">重置密码</el-button>
            <el-button
              v-if="row.online_sessions > 0"
              link
              type="warning"
              @click="handleKickUser(row)"
            >
              强制下线
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          layout="total, sizes, prev, pager, next"
          :page-sizes="[10, 20, 50]"
          @current-change="loadAccounts"
          @size-change="loadAccounts"
        />
      </div>
    </div>

    <el-dialog v-model="createDialogVisible" title="管理员分配新用户" width="500px" destroy-on-close>
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="100px">
        <el-form-item label="用户邮箱" prop="email">
          <el-input
            v-model="createForm.email"
            placeholder="请输入用户邮箱地址"
            @blur="handleCheckCreateEmail"
          >
            <template #append>
              <el-button :loading="emailCheckLoading" @click="handleCheckCreateEmail">检测</el-button>
            </template>
          </el-input>
        </el-form-item>

        <el-form-item v-if="emailAnalysis" label="风控评估">
          <el-alert
            :title="`${emailAnalysis.provider}（${emailAnalysis.trust_score} 分）：${emailAnalysis.summary}`"
            :type="emailAnalysis.allowed ? 'success' : 'warning'"
            :closable="false"
            show-icon
          />
        </el-form-item>

        <el-form-item label="用户昵称" prop="nickname">
          <el-input v-model="createForm.nickname" placeholder="例如：张三" maxlength="32" />
        </el-form-item>

        <el-form-item label="登录用户名" prop="username">
          <el-input v-model="createForm.username" placeholder="可选，留空仅使用邮箱登录" maxlength="32" />
        </el-form-item>

        <el-form-item label="初始密码" prop="password">
          <el-input v-model="createForm.password" placeholder="至少 8 位且包含字母与数字">
            <template #append>
              <el-button @click="generateStrongPassword">随机生成</el-button>
            </template>
          </el-input>
        </el-form-item>

        <el-form-item label="分配角色" prop="role">
          <el-radio-group v-model="createForm.role">
            <el-radio value="user">普通用户</el-radio>
            <el-radio value="admin">管理员</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="邮箱策略">
          <el-checkbox v-model="createForm.allow_non_mainstream_email">
            管理员特权：允许为内部成员分配非常规 / 自定义域名邮箱
          </el-checkbox>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreateSubmit">
          确认分配创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.search-bar {
  margin-bottom: 12px;
}

.user-cell {
  display: flex;
  flex-direction: column;
}

.sub-text {
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.trust-cell {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.trust-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
}

.provider-text {
  color: var(--ailove-ink-secondary);
  font-weight: 500;
}

.trust-num {
  font-weight: 600;
}

.trust-num.is-high {
  color: var(--ailove-success);
}

.trust-num.is-mid {
  color: var(--ailove-warning);
}

.trust-num.is-low {
  color: var(--ailove-danger);
}

.trust-bar {
  height: 5px;
  border-radius: 999px;
  background: var(--ailove-canvas);
  overflow: hidden;
}

.trust-fill {
  height: 100%;
  border-radius: 999px;
}

.trust-fill.is-high {
  background: var(--ailove-success);
}

.trust-fill.is-mid {
  background: var(--ailove-accent-amber);
}

.trust-fill.is-low {
  background: var(--ailove-danger);
}

.pagination-wrap {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
