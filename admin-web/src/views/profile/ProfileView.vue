<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from '@/plugins/element-plus'
import {
  changeMyPassword,
  fetchMyLoginLogs,
  fetchMySessions,
  revokeMySession,
  revokeOtherSessions,
  updateMyProfile,
  type LoginLogItem,
  type SessionItem,
} from '@/api/auth'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const appStore = useAppStore()
const authStore = useAuthStore()
const user = computed(() => authStore.user)
const passwordMinLength = computed(() => Math.max(6, appStore.publicConfig.password_min_length || 8))

const activeTab = ref('profile')

const nicknameForm = reactive({ nickname: '' })
const savingProfile = ref(false)

const sessionsLoading = ref(false)
const sessions = ref<SessionItem[]>([])
const maxSessions = ref(5)
const ttlHours = ref(24)

const pwdFormRef = ref<FormInstance>()
const changingPwd = ref(false)
const pwdForm = reactive({
  current_password: '',
  new_password: '',
  confirm_password: '',
  logout_other_devices: true,
})

const pwdRules = computed<FormRules>(() => ({
  current_password: [{ required: true, message: '请输入当前原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    {
      min: passwordMinLength.value,
      message: `密码至少 ${passwordMinLength.value} 位`,
      trigger: 'blur',
    },
    {
      validator: (_rule, value: string, callback) => {
        if (value && (!/[A-Za-z]/.test(value) || !/\d/.test(value))) {
          callback(new Error('新密码必须同时包含字母和数字'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
  confirm_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value: string, callback) => {
        if (value !== pwdForm.new_password) {
          callback(new Error('两次输入的新密码不一致'))
        } else {
          callback()
        }
      },
      trigger: 'blur',
    },
  ],
}))

const logsLoading = ref(false)
const loginLogs = ref<LoginLogItem[]>([])

const sourceText = computed(() => {
  const s = user.value?.register_source
  if (s === 'email_register') return '正规邮箱自助注册'
  if (s === 'admin_assigned') return '管理员后台分配'
  return '系统内置初始化'
})

const roleText = computed(() => {
  if (user.value?.role_name) return user.value.role_name
  const r = user.value?.role
  if (r === 'super_admin') return '超级管理员'
  if (r === 'admin') return '系统管理员'
  if (r === 'operator') return '运营审计员'
  return '普通用户'
})

const otherDeviceCount = computed(() => sessions.value.filter((s) => !s.is_current).length)

function formatRemaining(seconds: number): string {
  if (seconds <= 0) return '即将过期'
  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  if (hrs > 0) return `${hrs}h ${mins}m`
  return `${Math.max(1, mins)}m`
}

function formatTime(iso: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { hour12: false })
}

async function loadSessions() {
  sessionsLoading.value = true
  try {
    const res = await fetchMySessions()
    sessions.value = res.items
    maxSessions.value = res.max_sessions
    ttlHours.value = res.ttl_hours
  } finally {
    sessionsLoading.value = false
  }
}

async function loadLoginLogs() {
  logsLoading.value = true
  try {
    const res = await fetchMyLoginLogs()
    loginLogs.value = res.items
  } finally {
    logsLoading.value = false
  }
}

async function handleSaveNickname() {
  const clean = nicknameForm.nickname.trim()
  if (!clean) {
    ElMessage.warning('昵称不能为空')
    return
  }
  savingProfile.value = true
  try {
    const updated = await updateMyProfile(clean)
    if (authStore.user) {
      authStore.user.nickname = updated.nickname
    }
    ElMessage.success('昵称已更新')
  } finally {
    savingProfile.value = false
  }
}

async function handleKickSession(item: SessionItem) {
  await ElMessageBox.confirm(
    `确认将设备「${item.device_label} (${item.ip})」踢下线？`,
    '远程下线确认',
    { confirmButtonText: '确认踢下线', cancelButtonText: '取消', type: 'warning' },
  )
  await revokeMySession(item.session_id)
  ElMessage.success('该设备已踢下线')
  await loadSessions()
}

async function handleRevokeOthers() {
  await ElMessageBox.confirm(
    `确认将除当前设备外的其余 ${otherDeviceCount.value} 台设备全部下线？`,
    '一键下线确认',
    { confirmButtonText: '全部下线', cancelButtonText: '取消', type: 'warning' },
  )
  const res = await revokeOtherSessions()
  ElMessage.success(`已成功下线 ${res.revoked_count} 台其他设备`)
  await loadSessions()
}

async function handleChangePassword() {
  const valid = await pwdFormRef.value?.validate().catch(() => false)
  if (!valid) return

  changingPwd.value = true
  try {
    const res = await changeMyPassword({
      current_password: pwdForm.current_password,
      new_password: pwdForm.new_password,
      logout_other_devices: pwdForm.logout_other_devices,
    })
    ElMessage.success(
      res.revoked_other_devices > 0
        ? `密码修改成功，并已下线其他 ${res.revoked_other_devices} 台设备`
        : '密码修改成功',
    )
    pwdForm.current_password = ''
    pwdForm.new_password = ''
    pwdForm.confirm_password = ''
    await loadSessions()
  } finally {
    changingPwd.value = false
  }
}

function handleTabChange(name: string | number) {
  if (name === 'sessions') void loadSessions()
  if (name === 'logs') void loadLoginLogs()
}

onMounted(async () => {
  await authStore.loadProfile()
  nicknameForm.nickname = authStore.user?.nickname || ''
  void loadSessions()
})
</script>

<template>
  <div>
    <!-- 温润个人档案头图条 -->
    <div class="profile-hero">
      <div class="hero-left">
        <div class="hero-avatar">
          {{ (user?.nickname || 'U').slice(0, 1).toUpperCase() }}
        </div>
        <div>
          <div class="hero-title-row">
            <h2>{{ user?.nickname || '加载中' }}</h2>
            <el-tag :type="authStore.isAdmin ? 'warning' : 'danger'" size="small" effect="light">
              {{ roleText }}
            </el-tag>
          </div>
          <div class="hero-meta">
            <span>{{ user?.email || '-' }}</span>
            <span>·</span>
            <span>{{ sourceText }}</span>
          </div>
        </div>
      </div>

      <div class="hero-metrics">
        <div class="hero-metric">
          <div class="hm-label">多端在线</div>
          <div class="hm-val mono-num">{{ sessions.length }} / {{ maxSessions }}</div>
        </div>
        <div class="hero-metric">
          <div class="hm-label">当前会话剩余（{{ ttlHours }}h）</div>
          <div class="hm-val mono-num">
            {{ formatRemaining(user?.session?.remaining_seconds ?? 86400) }}
          </div>
        </div>
        <div class="hero-metric">
          <div class="hm-label">邮箱可信分</div>
          <div class="hm-val mono-num is-trust">{{ user?.email_trust_score ?? 100 }}</div>
        </div>
      </div>
    </div>

    <div class="page-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="基本资料" name="profile">
          <el-descriptions :column="2" border style="margin-bottom: 22px">
            <el-descriptions-item label="绑定邮箱">
              <span class="mono-num">{{ user?.email || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="登录用户名">
              {{ user?.username || '使用邮箱登录' }}
            </el-descriptions-item>
            <el-descriptions-item label="邮箱服务商">
              {{ user?.email_provider || '-' }}
            </el-descriptions-item>
            <el-descriptions-item label="账号来源">
              <el-tag type="success" effect="light" size="small">{{ sourceText }}</el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <el-form :inline="true" :model="nicknameForm">
            <el-form-item label="修改显示昵称">
              <el-input v-model="nicknameForm.nickname" maxlength="32" style="width: 240px" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingProfile" @click="handleSaveNickname">
                保存昵称
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane :label="`在线设备 (${sessions.length})`" name="sessions">
          <div class="session-toolbar">
            <span class="toolbar-tip">
              支持最多 {{ maxSessions }} 端并发在线，超限自动淘汰最早会话；每端满 {{ ttlHours }} 小时自动过期。
            </span>
            <div class="toolbar-btns">
              <el-button size="small" icon="Refresh" @click="loadSessions">刷新</el-button>
              <el-button
                size="small"
                type="danger"
                plain
                :disabled="otherDeviceCount === 0"
                @click="handleRevokeOthers"
              >
                一键下线其他全部设备
              </el-button>
            </div>
          </div>

          <el-table v-loading="sessionsLoading" :data="sessions" stripe border>
            <el-table-column label="终端设备" min-width="180">
              <template #default="{ row }">
                <div class="device-cell">
                  <span class="status-dot is-live" />
                  <span>{{ row.device_label }}</span>
                  <el-tag v-if="row.is_current" size="small" type="success">当前设备</el-tag>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="登录 IP" width="150">
              <template #default="{ row }">
                <span class="mono-num">{{ row.ip }}</span>
              </template>
            </el-table-column>
            <el-table-column label="登录时间" width="175">
              <template #default="{ row }">
                <span class="mono-num">{{ formatTime(row.login_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="最近活跃" width="175">
              <template #default="{ row }">
                <span class="mono-num">{{ formatTime(row.last_active_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="剩余有效期" width="130">
              <template #default="{ row }">
                <el-tag size="small" type="info" class="mono-num">
                  {{ formatRemaining(row.remaining_seconds) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" fixed="right">
              <template #default="{ row }">
                <span v-if="row.is_current" class="muted">本机在线</span>
                <el-button v-else link type="danger" @click="handleKickSession(row)">
                  踢下线
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="修改密码" name="password">
          <el-form
            ref="pwdFormRef"
            :model="pwdForm"
            :rules="pwdRules"
            label-width="110px"
            style="max-width: 460px; margin-top: 8px"
          >
            <el-form-item label="当前原密码" prop="current_password">
              <el-input v-model="pwdForm.current_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="设置新密码" prop="new_password">
              <el-input
                v-model="pwdForm.new_password"
                type="password"
                show-password
                :placeholder="`至少 ${passwordMinLength} 位且包含字母与数字`"
              />
            </el-form-item>
            <el-form-item label="确认新密码" prop="confirm_password">
              <el-input v-model="pwdForm.confirm_password" type="password" show-password />
            </el-form-item>
            <el-form-item label="多端安全">
              <el-checkbox v-model="pwdForm.logout_other_devices">
                修改密码后自动下线其他已登录设备（推荐）
              </el-checkbox>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="changingPwd" @click="handleChangePassword">
                确认修改密码
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="登录安全日志" name="logs">
          <div class="session-toolbar">
            <span class="toolbar-tip">展示最近 20 条登录成功与失败风控审计记录</span>
            <el-button size="small" icon="Refresh" @click="loadLoginLogs">刷新记录</el-button>
          </div>

          <el-table v-loading="logsLoading" :data="loginLogs" stripe border>
            <el-table-column label="时间" width="180">
              <template #default="{ row }">
                <span class="mono-num">{{ formatTime(row.created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="device_label" label="终端设备" min-width="150" />
            <el-table-column label="IP 地址" width="150">
              <template #default="{ row }">
                <span class="mono-num">{{ row.ip }}</span>
              </template>
            </el-table-column>
            <el-table-column label="结果" width="95">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small">
                  {{ row.status === 'success' ? '成功' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="fail_reason" label="备注 / 失败原因" min-width="180">
              <template #default="{ row }">{{ row.fail_reason || '正常通过验证' }}</template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style scoped>
.profile-hero {
  background: linear-gradient(135deg, #ffffff 0%, #fff7f8 55%, #fffbf2 100%);
  border: 1px solid var(--ailove-border);
  border-radius: var(--ailove-radius-lg);
  box-shadow: var(--ailove-shadow-card);
  padding: 24px 26px;
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.hero-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.hero-avatar {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: linear-gradient(135deg, #e14b68 0%, #c83553 60%, #d97706 140%);
  color: #ffffff;
  font-family: var(--ailove-font-display);
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--ailove-shadow-brand);
}

.hero-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.hero-title-row h2 {
  margin: 0;
  font-family: var(--ailove-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.hero-meta {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--ailove-ink-muted);
}

.hero-metrics {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.hero-metric {
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid var(--ailove-border);
  border-radius: 12px;
  padding: 10px 16px;
  min-width: 126px;
}

.hm-label {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.hm-val {
  margin-top: 4px;
  font-size: 18px;
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.hm-val.is-trust {
  color: var(--ailove-success);
}

.session-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}

.toolbar-tip {
  font-size: 13px;
  color: var(--ailove-ink-muted);
}

.toolbar-btns {
  display: flex;
  gap: 8px;
}

.device-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.muted {
  font-size: 12px;
  color: var(--ailove-ink-muted);
}
</style>
