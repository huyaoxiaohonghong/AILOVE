<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from '@/plugins/element-plus'
import {
  createAiConfig,
  deleteAiConfig,
  fetchAiConfigs,
  fetchAiProviders,
  setDefaultAiConfig,
  testAiConfig,
  updateAiConfig,
  type AIModelConfigItem,
  type AIProtocol,
  type AIProviderInfo,
} from '@/api/ai'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const canManage = computed(() => authStore.hasPermission('ai:config:manage'))

const loading = ref(false)
const providers = ref<AIProviderInfo[]>([])
const configs = ref<AIModelConfigItem[]>([])
const testingId = ref<number | null>(null)

const dialogVisible = ref(false)
const saving = ref(false)
const editingId = ref<number | null>(null)
const editingHasKey = ref(false)
const formRef = ref<FormInstance>()

const form = reactive({
  name: '',
  provider: 'deepseek',
  protocol: 'openai' as AIProtocol,
  model_name: 'deepseek-flash',
  base_url: 'https://api.deepseek.com',
  api_key: '',
  clear_api_key: false,
  temperature: 0.7,
  top_p: 1.0,
  max_tokens: 4096,
  timeout_seconds: 60,
  max_history_messages: 20,
  system_prompt: '你是 AILOVE 智能助手，请用清晰、温暖、专业的中文回答用户问题。',
  is_enabled: true,
  is_default: false,
})

const rules: FormRules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择模型提供商', trigger: 'change' }],
  protocol: [{ required: true, message: '请选择接口协议', trigger: 'change' }],
  model_name: [{ required: true, message: '请选择或输入模型名', trigger: 'blur' }],
  base_url: [{ required: true, message: '请输入 API Base URL', trigger: 'blur' }],
}

const activeProviders = computed(() => providers.value.filter((p) => p.status === 'active'))
const plannedProviders = computed(() => providers.value.filter((p) => p.status === 'planned'))
const defaultConfig = computed(
  () => configs.value.find((c) => c.is_default) ?? configs.value[0] ?? null,
)
const currentProviderObj = computed(
  () => activeProviders.value.find((p) => p.code === form.provider) ?? activeProviders.value[0] ?? null,
)
const isLegacyReasoner = computed(() => form.model_name.trim().toLowerCase() === 'deepseek-reasoner')
const isV4ProSelected = computed(() => form.model_name.trim().toLowerCase() === 'deepseek-v4-pro')

function protocolLabel(protocol?: string) {
  return protocol === 'anthropic' ? 'Anthropic 协议' : 'OpenAI 协议'
}

async function loadAll() {
  loading.value = true
  try {
    const [provRes, cfgRes] = await Promise.all([fetchAiProviders(), fetchAiConfigs()])
    providers.value = provRes.items
    configs.value = cfgRes.items
  } finally {
    loading.value = false
  }
}

function openCreateDialog(presetModelId = 'deepseek-flash', presetProtocol: AIProtocol = 'openai') {
  editingId.value = null
  editingHasKey.value = false
  const deepseek = activeProviders.value.find((p) => p.code === 'deepseek')
  const preset = deepseek?.models.find((m) => m.id === presetModelId)
  const endpoints = deepseek?.protocol_endpoints ?? {
    openai: 'https://api.deepseek.com',
    anthropic: 'https://api.deepseek.com/anthropic',
  }

  form.name =
    presetModelId === 'deepseek-v4-pro'
      ? `DeepSeek V4 Pro (${presetProtocol === 'anthropic' ? 'Anthropic' : 'OpenAI'})`
      : `DeepSeek Flash (${presetProtocol === 'anthropic' ? 'Anthropic' : 'OpenAI'})`
  form.provider = 'deepseek'
  form.protocol = presetProtocol
  form.model_name = presetModelId
  form.base_url = endpoints[presetProtocol] || deepseek?.default_base_url || 'https://api.deepseek.com'
  form.api_key = ''
  form.clear_api_key = false
  form.temperature = 0.7
  form.top_p = 1.0
  form.max_tokens = preset?.default_max_tokens ?? 4096
  form.timeout_seconds = 60
  form.max_history_messages = 20
  form.system_prompt = '你是 AILOVE 智能助手，请用清晰、温暖、专业的中文回答用户问题。'
  form.is_enabled = true
  form.is_default = configs.value.length === 0
  dialogVisible.value = true
}

function openEditDialog(row: AIModelConfigItem) {
  editingId.value = row.id
  editingHasKey.value = row.has_api_key
  form.name = row.name
  form.provider = row.provider
  form.protocol = row.protocol || 'openai'
  form.model_name = row.model_name
  form.base_url = row.base_url
  form.api_key = ''
  form.clear_api_key = false
  form.temperature = row.temperature
  form.top_p = row.top_p
  form.max_tokens = row.max_tokens
  form.timeout_seconds = row.timeout_seconds
  form.max_history_messages = row.max_history_messages
  form.system_prompt = row.system_prompt
  form.is_enabled = row.is_enabled
  form.is_default = row.is_default
  dialogVisible.value = true
}

function handleProtocolChange(proto: string | number | boolean | undefined) {
  const nextProto: AIProtocol = proto === 'anthropic' ? 'anthropic' : 'openai'
  const endpoints = currentProviderObj.value?.protocol_endpoints ?? {
    openai: 'https://api.deepseek.com',
    anthropic: 'https://api.deepseek.com/anthropic',
  }
  const matched = endpoints[nextProto]
  if (matched) {
    form.base_url = matched
  }
}

function handleModelPresetChange(modelId: string) {
  const preset = currentProviderObj.value?.models.find((m) => m.id === modelId)
  if (preset) {
    form.max_tokens = preset.default_max_tokens
  }
}

async function handleSave() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  saving.value = true
  try {
    if (editingId.value === null) {
      await createAiConfig({
        name: form.name.trim(),
        provider: form.provider,
        protocol: form.protocol,
        model_name: form.model_name.trim(),
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim(),
        temperature: form.temperature,
        top_p: form.top_p,
        max_tokens: form.max_tokens,
        timeout_seconds: form.timeout_seconds,
        max_history_messages: form.max_history_messages,
        system_prompt: form.system_prompt.trim(),
        is_enabled: form.is_enabled,
        is_default: form.is_default,
      })
      ElMessage.success('DeepSeek 模型配置已创建并热生效')
    } else {
      await updateAiConfig(editingId.value, {
        name: form.name.trim(),
        protocol: form.protocol,
        model_name: form.model_name.trim(),
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim() || undefined,
        clear_api_key: form.clear_api_key,
        temperature: form.temperature,
        top_p: form.top_p,
        max_tokens: form.max_tokens,
        timeout_seconds: form.timeout_seconds,
        max_history_messages: form.max_history_messages,
        system_prompt: form.system_prompt.trim(),
        is_enabled: form.is_enabled,
        is_default: form.is_default,
      })
      ElMessage.success('配置已保存并即时生效（无需重启服务）')
    }
    dialogVisible.value = false
    await loadAll()
  } finally {
    saving.value = false
  }
}

async function handleTest(row: AIModelConfigItem) {
  testingId.value = row.id
  try {
    const res = await testAiConfig(row.id)
    if (res.success) {
      ElMessage.success(res.message)
    } else {
      ElMessage.warning(res.message)
    }
    await loadAll()
  } finally {
    testingId.value = null
  }
}

async function handleSetDefault(row: AIModelConfigItem) {
  await setDefaultAiConfig(row.id)
  ElMessage.success(`已将「${row.name}」设为全局默认模型`)
  await loadAll()
}

async function handleDelete(row: AIModelConfigItem) {
  try {
    await ElMessageBox.confirm(`确认删除模型配置「${row.name}」？`, '删除确认', {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteAiConfig(row.id)
    ElMessage.success('模型配置已删除')
    await loadAll()
  } catch {
    // 取消
  }
}

onMounted(() => {
  void loadAll()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <h2 class="page-title">AI 模型配置中心</h2>
        <p class="page-subtitle">
          统一管理大模型 API 密钥（Fernet 加密落库）、双协议端点切换与连通探测；首期内置 DeepSeek (deepseek-flash / deepseek-v4-pro)
        </p>
      </div>
      <div class="header-actions">
        <el-button plain icon="ChatDotRound" @click="router.push('/ai-playground')">
          打开 AI 调试台
        </el-button>
        <el-button
          v-if="canManage"
          type="primary"
          icon="Plus"
          @click="openCreateDialog('deepseek-flash', 'openai')"
        >
          新增 DeepSeek 配置
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!canManage"
      title="当前账号仅拥有「AI 模型配置查看」权限，新增、编辑、测速与切换默认模型已锁定。"
      type="info"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <!-- 当前生效默认引擎横幅 -->
    <div v-if="defaultConfig" class="active-engine-banner">
      <div class="engine-left">
        <div class="engine-badge">
          <span
            class="status-dot"
            :class="defaultConfig.has_api_key ? 'is-live' : 'is-warn'"
          />
          <span>全局默认生效引擎</span>
        </div>
        <div class="engine-title-row">
          <h3>{{ defaultConfig.name }}</h3>
          <el-tag size="small" type="danger" effect="light" class="mono-num">
            {{ defaultConfig.provider }} / {{ defaultConfig.model_name }}
          </el-tag>
          <el-tag
            size="small"
            :type="defaultConfig.protocol === 'anthropic' ? 'warning' : 'info'"
            effect="plain"
          >
            {{ protocolLabel(defaultConfig.protocol) }}
          </el-tag>
        </div>
        <div class="engine-meta">
          <span>
            API Key：
            <strong class="mono-num">
              {{ defaultConfig.has_api_key ? defaultConfig.api_key_masked : '未配置（演示模式）' }}
            </strong>
          </span>
          <span>·</span>
          <span>Base URL：<code class="mono-num">{{ defaultConfig.base_url }}</code></span>
          <template v-if="defaultConfig.last_test_latency_ms !== null">
            <span>·</span>
            <span>最近测速：<strong class="mono-num">{{ defaultConfig.last_test_latency_ms }} ms</strong></span>
          </template>
        </div>
      </div>

      <div v-if="canManage" class="engine-actions">
        <el-button
          plain
          :loading="testingId === defaultConfig.id"
          @click="handleTest(defaultConfig)"
        >
          测试连通
        </el-button>
        <el-button type="primary" @click="openEditDialog(defaultConfig)">
          {{ defaultConfig.has_api_key ? '编辑配置' : '立即填入 API Key' }}
        </el-button>
      </div>
    </div>

    <!-- 提供商注册表（DeepSeek 已开放 + 多模型可扩展预留） -->
    <div class="provider-section">
      <div class="section-caption">模型提供商注册表（Adapter 可插拔架构，后续新增模型零改表）</div>
      <div class="provider-grid">
        <div
          v-for="p in activeProviders"
          :key="p.code"
          class="provider-card is-active-provider"
        >
          <div class="prov-head">
            <div>
              <div class="prov-name">{{ p.name }}</div>
              <div class="prov-proto mono-num">{{ p.protocol }}</div>
            </div>
            <el-tag type="success" size="small">当前已支持</el-tag>
          </div>
          <p class="prov-desc">{{ p.description }}</p>
          <div v-if="p.protocol_endpoints" class="endpoint-chips mono-num">
            <span>OpenAI: {{ p.protocol_endpoints.openai }}</span>
            <span>Anthropic: {{ p.protocol_endpoints.anthropic }}</span>
          </div>
          <div class="prov-models">
            <template v-if="canManage">
              <el-button
                v-for="m in p.models"
                :key="m.id"
                size="small"
                plain
                @click="openCreateDialog(m.id, 'openai')"
              >
                + {{ m.id }}
              </el-button>
            </template>
            <el-tag v-for="m in (canManage ? [] : p.models)" :key="m.id" size="small" effect="plain">
              {{ m.id }}
            </el-tag>
            <a :href="p.docs_url" target="_blank" rel="noreferrer" class="key-link">
              申请 API Key ↗
            </a>
          </div>
        </div>

        <div
          v-for="p in plannedProviders"
          :key="p.code"
          class="provider-card is-planned"
        >
          <div class="prov-head">
            <div>
              <div class="prov-name">{{ p.name }}</div>
              <div class="prov-proto mono-num">{{ p.protocol }}</div>
            </div>
            <el-tag type="info" size="small" effect="plain">后续接入</el-tag>
          </div>
          <p class="prov-desc">{{ p.description }}</p>
        </div>
      </div>
    </div>

    <!-- 模型配置列表 -->
    <div class="page-card">
      <div class="list-head">
        <h3>已保存的模型配置（{{ configs.length }}）</h3>
        <el-button size="small" icon="Refresh" @click="loadAll">刷新</el-button>
      </div>

      <el-table :data="configs" stripe border>
        <el-table-column label="配置名称" min-width="180">
          <template #default="{ row }">
            <div class="name-cell">
              <strong>{{ row.name }}</strong>
              <el-tag v-if="row.is_default" size="small" type="danger" effect="light">
                默认生效
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="模型与接口协议" min-width="235">
          <template #default="{ row }">
            <div class="model-cell">
              <div class="model-line">
                <span class="mono-num model-id">{{ row.provider }} / {{ row.model_name }}</span>
                <el-tag
                  size="small"
                  :type="row.protocol === 'anthropic' ? 'warning' : 'info'"
                  effect="plain"
                >
                  {{ row.protocol === 'anthropic' ? 'Anthropic' : 'OpenAI' }}
                </el-tag>
              </div>
              <span class="sub-url mono-num">{{ row.base_url }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="API Key" width="165">
          <template #default="{ row }">
            <el-tag v-if="row.has_api_key" type="success" size="small" effect="plain" class="mono-num">
              {{ row.api_key_masked }}
            </el-tag>
            <el-tag v-else type="warning" size="small" effect="plain">未填写 Key</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="核心参数" min-width="175">
          <template #default="{ row }">
            <div class="param-pills mono-num">
              <span>T={{ row.temperature }}</span>
              <span>Max={{ row.max_tokens }}</span>
              <span>Ctx={{ row.max_history_messages }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="连通状态" min-width="150">
          <template #default="{ row }">
            <div class="test-cell">
              <el-tag
                size="small"
                :type="
                  row.last_test_status === 'ok'
                    ? 'success'
                    : row.last_test_status === 'failed'
                      ? 'danger'
                      : 'info'
                "
              >
                {{
                  row.last_test_status === 'ok'
                    ? `通过 · ${row.last_test_latency_ms ?? 0}ms`
                    : row.last_test_status === 'failed'
                      ? '测试失败'
                      : '未测试'
                }}
              </el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column v-if="canManage" label="操作" width="235" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="primary"
              :loading="testingId === row.id"
              @click="handleTest(row)"
            >
              测试连通
            </el-button>
            <el-button
              v-if="!row.is_default"
              link
              type="success"
              @click="handleSetDefault(row)"
            >
              设为默认
            </el-button>
            <el-button link type="primary" @click="openEditDialog(row)">编辑</el-button>
            <el-button
              v-if="configs.length > 1"
              link
              type="danger"
              @click="handleDelete(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增 / 编辑配置弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新增 DeepSeek 模型配置' : '编辑 AI 模型配置'"
      width="600px"
      destroy-on-close
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="118px">
        <el-form-item label="配置名称" prop="name">
          <el-input v-model="form.name" placeholder="例如：DeepSeek Flash 主力对话" maxlength="64" />
        </el-form-item>

        <el-form-item label="模型提供商" prop="provider">
          <el-select v-model="form.provider" :disabled="editingId !== null" style="width: 100%">
            <el-option
              v-for="p in activeProviders"
              :key="p.code"
              :label="`${p.name} (${p.protocol})`"
              :value="p.code"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="API 接口协议" prop="protocol">
          <el-radio-group v-model="form.protocol" @change="handleProtocolChange">
            <el-radio-button value="openai">OpenAI 协议</el-radio-button>
            <el-radio-button value="anthropic">Anthropic 协议</el-radio-button>
          </el-radio-group>
          <span class="proto-hint mono-num">
            {{
              form.protocol === 'anthropic'
                ? 'https://api.deepseek.com/anthropic'
                : 'https://api.deepseek.com'
            }}
          </span>
        </el-form-item>

        <el-form-item label="模型名称" prop="model_name">
          <el-select
            v-model="form.model_name"
            filterable
            allow-create
            default-first-option
            style="width: 100%"
            @change="handleModelPresetChange"
          >
            <el-option
              v-for="m in currentProviderObj?.models ?? []"
              :key="m.id"
              :label="m.label"
              :value="m.id"
            >
              <div class="preset-opt">
                <span>{{ m.label }}</span>
                <span class="preset-sub">{{ m.description }}</span>
              </div>
            </el-option>
          </el-select>
        </el-form-item>

        <el-alert
          v-if="isV4ProSelected"
          title="已选择 DeepSeek V4 Pro：支持深度思考推理链（自动兼容 OpenAI reasoning_content 与 Anthropic thinking 块）。"
          type="info"
          show-icon
          :closable="false"
          style="margin-bottom: 14px"
        />

        <el-form-item label="API Base URL" prop="base_url">
          <el-input
            v-model="form.base_url"
            :placeholder="
              form.protocol === 'anthropic'
                ? 'https://api.deepseek.com/anthropic'
                : 'https://api.deepseek.com'
            "
          />
        </el-form-item>

        <el-form-item label="API Key" prop="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="
              editingId !== null && editingHasKey
                ? '已加密保存，留空则保持原 Key 不变'
                : '请输入 DeepSeek API Key (sk-...)'
            "
          />
          <div class="key-helper-row">
            <a
              href="https://platform.deepseek.com/api_keys"
              target="_blank"
              rel="noreferrer"
              class="key-apply-link"
            >
              前往 DeepSeek 开放平台申请 API Key ↗
            </a>
            <el-checkbox
              v-if="editingId !== null && editingHasKey"
              v-model="form.clear_api_key"
            >
              清空已保存 Key
            </el-checkbox>
          </div>
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="采样温度">
              <el-slider
                v-model="form.temperature"
                :min="0"
                :max="2"
                :step="0.1"
                :disabled="isLegacyReasoner"
                show-input
                :show-input-controls="false"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="最大输出 Token">
              <el-input-number
                v-model="form.max_tokens"
                :min="128"
                :max="32768"
                :step="512"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="上下文记忆条数">
              <el-input-number
                v-model="form.max_history_messages"
                :min="2"
                :max="60"
                :step="2"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="超时时间 (秒)">
              <el-input-number
                v-model="form.timeout_seconds"
                :min="10"
                :max="240"
                :step="10"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="默认系统提示词">
          <el-input
            v-model="form.system_prompt"
            type="textarea"
            :rows="3"
            placeholder="定义 AI 的角色人设与回复风格"
          />
        </el-form-item>

        <el-form-item label="启用与默认">
          <el-switch v-model="form.is_enabled" active-text="启用" style="margin-right: 20px" />
          <el-switch v-model="form.is_default" active-text="设为全局默认模型" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存并热生效</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  gap: 10px;
}

.active-engine-banner {
  background: linear-gradient(135deg, #ffffff 0%, #fff4f6 60%, #fffaf0 100%);
  border: 1px solid var(--ailove-brand-100);
  border-radius: var(--ailove-radius-lg);
  box-shadow: var(--ailove-shadow-card);
  padding: 22px 24px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
}

.engine-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ailove-brand-600);
  margin-bottom: 8px;
}

.engine-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.engine-title-row h3 {
  margin: 0;
  font-family: var(--ailove-font-display);
  font-size: 19px;
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.engine-meta {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
}

.engine-meta code {
  background: rgba(26, 22, 29, 0.05);
  padding: 2px 6px;
  border-radius: 5px;
}

.engine-actions {
  display: flex;
  gap: 10px;
}

.provider-section {
  margin-bottom: 20px;
}

.section-caption {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ailove-ink-muted);
  margin-bottom: 10px;
}

.provider-grid {
  display: grid;
  grid-template-columns: 1.75fr repeat(4, 1fr);
  gap: 12px;
}

.provider-card {
  background: var(--ailove-surface);
  border: 1px solid var(--ailove-border);
  border-radius: 14px;
  padding: 15px 16px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 10px;
}

.provider-card.is-active-provider {
  border-color: var(--ailove-brand-200);
  box-shadow: var(--ailove-shadow-card);
}

.provider-card.is-planned {
  background: var(--ailove-subtle);
  opacity: 0.82;
}

.prov-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.prov-name {
  font-family: var(--ailove-font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.prov-proto {
  font-size: 11px;
  color: var(--ailove-ink-muted);
  margin-top: 2px;
}

.prov-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: var(--ailove-ink-secondary);
}

.endpoint-chips {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--ailove-ink-secondary);
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  border-radius: 8px;
  padding: 7px 9px;
}

.prov-models {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.key-link {
  font-size: 12px;
  font-weight: 500;
  margin-left: auto;
}

.list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.list-head h3 {
  margin: 0;
  font-family: var(--ailove-font-display);
  font-size: 16px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.model-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.model-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.model-id {
  font-size: 13px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.sub-url {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.param-pills {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--ailove-ink-secondary);
}

.proto-hint {
  margin-left: 10px;
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.key-helper-row {
  width: 100%;
  margin-top: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.key-apply-link {
  font-size: 12px;
  font-weight: 500;
}

.preset-opt {
  display: flex;
  flex-direction: column;
  line-height: 1.35;
  padding: 2px 0;
}

.preset-sub {
  font-size: 11px;
  color: var(--ailove-ink-muted);
}

@media (max-width: 1100px) {
  .provider-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .provider-grid {
    grid-template-columns: 1fr;
  }
}
</style>
