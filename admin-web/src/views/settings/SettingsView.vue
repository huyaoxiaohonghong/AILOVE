<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  fetchHealth,
  fetchSystemConfigs,
  resetSystemConfigs,
  sendSmtpTestEmail,
  updateSystemConfigs,
  type HealthData,
  type SysConfigGroup,
} from '@/api/system'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'

const appStore = useAppStore()
const authStore = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const activeTab = ref('site')
const groups = ref<SysConfigGroup[]>([])
const draft = reactive<Record<string, string | number | boolean>>({})
const health = ref<HealthData | null>(null)
const smtpTestEmail = ref('')
const smtpTesting = ref(false)

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api/v1'
const appTitle = import.meta.env.VITE_APP_TITLE || 'AILOVE 管理后台'
const canManage = computed(() => authStore.hasPermission('system:config:manage'))

function syncDraftFromGroups(nextGroups: SysConfigGroup[]) {
  for (const g of nextGroups) {
    for (const item of g.items) {
      draft[item.config_key] = item.value
    }
  }
}

async function loadAll() {
  loading.value = true
  try {
    const [cfgRes, healthRes] = await Promise.all([fetchSystemConfigs(), fetchHealth()])
    groups.value = cfgRes.groups
    syncDraftFromGroups(cfgRes.groups)
    health.value = healthRes
  } finally {
    loading.value = false
  }
}

async function handleSaveGroup(group: SysConfigGroup) {
  const payload: Record<string, string | number | boolean> = {}
  for (const item of group.items) {
    const val = draft[item.config_key]
    if (item.is_secret) {
      if (typeof val === 'string' && val.trim()) {
        payload[item.config_key] = val.trim()
      }
      continue
    }
    payload[item.config_key] = val ?? item.value
  }
  saving.value = true
  try {
    const res = await updateSystemConfigs(payload)
    groups.value = res.groups
    syncDraftFromGroups(res.groups)
    await appStore.loadPublicConfig()
    ElMessage.success(`「${group.label}」配置已保存并即时热生效`)
  } finally {
    saving.value = false
  }
}

async function handleTestSmtp() {
  const target = smtpTestEmail.value.trim()
  if (!target || !target.includes('@')) {
    ElMessage.warning('请输入接收测试邮件的有效邮箱地址')
    return
  }
  smtpTesting.value = true
  try {
    const res = await sendSmtpTestEmail(target)
    ElMessage.success(
      `测试邮件已发往 ${res.to_email}（${res.host}:${res.port}，耗时 ${res.latency_ms}ms）`,
    )
  } finally {
    smtpTesting.value = false
  }
}

async function handleResetGroup(group: SysConfigGroup) {
  try {
    await ElMessageBox.confirm(
      `确认将「${group.label}」全部配置项恢复为系统默认值？`,
      '恢复默认配置',
      { confirmButtonText: '确认恢复', cancelButtonText: '取消', type: 'warning' },
    )
    saving.value = true
    const res = await resetSystemConfigs(group.group)
    groups.value = res.groups
    syncDraftFromGroups(res.groups)
    await appStore.loadPublicConfig()
    ElMessage.success(`已恢复「${group.label}」默认配置`)
  } catch {
    // 取消
  } finally {
    saving.value = false
  }
}

async function refreshHealth() {
  health.value = await fetchHealth()
  ElMessage.success('系统健康探针已刷新')
}

onMounted(() => {
  void loadAll()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <h2 class="page-title">动态系统配置中心</h2>
        <p class="page-subtitle">
          集中管理站点品牌、多端会话安全、注册风控开关、AI 对话策略与日志留存；修改后经 Redis 秒级热生效
        </p>
      </div>
      <el-button icon="Refresh" @click="loadAll">刷新配置</el-button>
    </div>

    <el-alert
      v-if="!canManage"
      title="当前账号仅拥有「系统配置查看」权限，修改保存按钮已锁定。"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <div class="page-card">
      <el-tabs v-model="activeTab">
        <el-tab-pane
          v-for="group in groups"
          :key="group.group"
          :label="group.label"
          :name="group.group"
        >
          <div class="config-list">
            <div v-for="item in group.items" :key="item.config_key" class="config-row">
              <div class="config-meta">
                <div class="config-title-line">
                  <span class="config-label">{{ item.label }}</span>
                  <code class="config-key mono-num">{{ item.config_key }}</code>
                  <el-tag v-if="item.is_public" size="small" type="success" effect="plain">
                    公共可见
                  </el-tag>
                  <el-tag v-if="item.is_secret && item.has_secret" size="small" type="warning" effect="plain">
                    已加密 · {{ item.masked_value }}
                  </el-tag>
                </div>
                <p class="config-desc">{{ item.description }}</p>
              </div>

              <div class="config-control">
                <template v-if="item.value_type === 'bool'">
                  <el-switch
                    v-model="draft[item.config_key]"
                    :disabled="!canManage"
                    active-text="开启"
                    inactive-text="关闭"
                  />
                </template>
                <template v-else-if="item.value_type === 'int'">
                  <el-input-number
                    v-model="(draft[item.config_key] as number)"
                    :min="item.min_val ?? undefined"
                    :max="item.max_val ?? undefined"
                    :disabled="!canManage"
                    style="width: 180px"
                  />
                </template>
                <template v-else-if="item.config_key === 'email.smtp_security'">
                  <el-select
                    v-model="(draft[item.config_key] as string)"
                    :disabled="!canManage"
                    style="width: 240px"
                  >
                    <el-option label="SSL 加密 (推荐 465)" value="ssl" />
                    <el-option label="STARTTLS (常见 587)" value="starttls" />
                    <el-option label="无加密 (仅内网调试)" value="none" />
                  </el-select>
                </template>
                <template v-else-if="item.is_secret">
                  <el-input
                    v-model="(draft[item.config_key] as string)"
                    type="password"
                    show-password
                    autocomplete="new-password"
                    :disabled="!canManage"
                    :placeholder="
                      item.has_secret
                        ? '已加密保存（留空则保持原密钥不变）'
                        : '请输入 SMTP 授权码或密码'
                    "
                    clearable
                    style="width: 300px"
                  />
                </template>
                <template v-else>
                  <el-input
                    v-model="(draft[item.config_key] as string)"
                    :disabled="!canManage"
                    :placeholder="`默认：${item.default_value || '空'}`"
                    clearable
                    style="width: 300px"
                  />
                </template>
              </div>
            </div>
          </div>

          <div v-if="group.group === 'email' && canManage" class="smtp-test-box">
            <div class="smtp-test-info">
              <strong>SMTP 连通性测试</strong>
              <span>请先点击下方「保存并热生效」保存参数，再输入收件邮箱验证发信通道。</span>
            </div>
            <div class="smtp-test-actions">
              <el-input
                v-model="smtpTestEmail"
                placeholder="输入接收测试邮件的邮箱地址"
                clearable
                style="width: 260px"
              />
              <el-button type="primary" plain :loading="smtpTesting" @click="handleTestSmtp">
                发送测试邮件
              </el-button>
            </div>
          </div>

          <div class="tab-footer">
            <el-button
              v-if="canManage"
              plain
              :disabled="saving"
              @click="handleResetGroup(group)"
            >
              恢复本组默认
            </el-button>
            <el-button
              v-if="canManage"
              type="primary"
              :loading="saving"
              @click="handleSaveGroup(group)"
            >
              保存并热生效
            </el-button>
          </div>
        </el-tab-pane>

        <el-tab-pane label="运行健康检测" name="health">
          <div class="health-head">
            <span class="health-sub">实时检测后端环境变量、MySQL、Redis 及 LangChain 默认模型引擎状态</span>
            <el-button size="small" icon="Refresh" @click="refreshHealth">重新探测</el-button>
          </div>

          <el-descriptions :column="2" border>
            <el-descriptions-item label="前端应用名">{{ appTitle }}</el-descriptions-item>
            <el-descriptions-item label="API Base URL">
              <span class="mono-num">{{ apiBaseUrl }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="后端服务名">{{ health?.app || '-' }}</el-descriptions-item>
            <el-descriptions-item label="运行环境">
              <span class="mono-num">{{ health?.env || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="综合健康状态">
              <el-tag :type="health?.status === 'ok' ? 'success' : 'warning'">
                {{ health?.status || '-' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="最近探测时间">
              <span class="mono-num">{{ health?.timestamp || '-' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="MySQL 状态">
              <el-tag :type="health?.services.mysql.healthy ? 'success' : 'danger'" size="small">
                {{ health?.services.mysql.status || '-' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Redis 状态">
              <el-tag :type="health?.services.redis.healthy ? 'success' : 'warning'" size="small">
                {{ health?.services.redis.status || '-' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<style scoped>
.config-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 6px;
}

.config-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 16px 18px;
  border-radius: 12px;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  flex-wrap: wrap;
}

.config-meta {
  flex: 1;
  min-width: 260px;
}

.config-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.config-label {
  font-size: 14.5px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.config-key {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
  background: rgba(26, 22, 29, 0.05);
  padding: 2px 7px;
  border-radius: 5px;
}

.config-desc {
  margin: 6px 0 0;
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
  line-height: 1.5;
}

.config-control {
  flex-shrink: 0;
}

.tab-footer {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.health-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 12px;
}

.health-sub {
  font-size: 13px;
  color: var(--ailove-ink-secondary);
}

.smtp-test-box {
  margin-top: 16px;
  padding: 14px 18px;
  border-radius: 12px;
  border: 1px dashed var(--ailove-brand-200);
  background: var(--ailove-brand-50);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.smtp-test-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
}

.smtp-test-info strong {
  font-size: 13.5px;
  color: var(--ailove-ink-primary);
}

.smtp-test-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
