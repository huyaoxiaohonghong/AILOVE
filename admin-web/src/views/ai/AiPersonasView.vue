<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from '@/plugins/element-plus'
import {
  ChatDotRound,
  Delete,
  EditPen,
  Plus,
  Refresh,
  Search,
} from '@element-plus/icons-vue'
import {
  createAdminPersona,
  deleteAdminPersona,
  fetchAdminPersonas,
  updateAdminPersona,
  type AIPersonaItem,
  type AIPersonaPayload,
  type PersonaCategory,
} from '@/api/ai'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const canManage = computed(() => authStore.hasPermission('ai:config:manage'))

const CATEGORY_OPTIONS: Array<{ value: PersonaCategory | 'all'; label: string }> = [
  { value: 'all', label: '全部情感智能体' },
  { value: 'chat_coach', label: '高情商话术' },
  { value: 'dating', label: '脱单约会' },
  { value: 'relationship', label: '关系维护' },
  { value: 'conflict', label: '吵架修复' },
  { value: 'healing', label: '情绪疗愈' },
]

const CATEGORY_MAP: Record<PersonaCategory, string> = {
  chat_coach: '高情商话术',
  dating: '脱单约会',
  relationship: '关系维护',
  conflict: '吵架修复',
  healing: '情绪疗愈',
}

const EMOJI_PRESETS = ['💘', '🌹', '💞', '🕊️', '🌙', '💌', '✨', '🫂', '🌸', '🎀']

const loading = ref(false)
const personas = ref<AIPersonaItem[]>([])
const activeCategory = ref<PersonaCategory | 'all'>('all')
const keyword = ref('')

const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)

const form = reactive({
  code: '',
  name: '',
  avatar_emoji: '💘',
  category: 'chat_coach' as PersonaCategory,
  description: '',
  system_prompt: '',
  starter_prompts: [''] as string[],
  override_temperature: false,
  temperature: 0.7,
  is_enabled: true,
  sort_order: 100,
})

const filteredList = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return personas.value.filter((item) => {
    if (activeCategory.value !== 'all' && item.category !== activeCategory.value) {
      return false
    }
    if (kw) {
      const hay = `${item.name} ${item.code} ${item.description}`.toLowerCase()
      if (!hay.includes(kw)) return false
    }
    return true
  })
})

async function loadPersonas() {
  loading.value = true
  try {
    const res = await fetchAdminPersonas()
    personas.value = res.items
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  editingId.value = null
  form.code = ''
  form.name = ''
  form.avatar_emoji = '💘'
  form.category = 'chat_coach'
  form.description = ''
  form.system_prompt = ''
  form.starter_prompts = ['']
  form.override_temperature = false
  form.temperature = 0.7
  form.is_enabled = true
  form.sort_order = 100
  dialogVisible.value = true
}

function openEditDialog(item: AIPersonaItem) {
  editingId.value = item.id
  form.code = item.code
  form.name = item.name
  form.avatar_emoji = item.avatar_emoji || '💘'
  form.category = item.category
  form.description = item.description
  form.system_prompt = item.system_prompt
  form.starter_prompts = item.starter_prompts.length > 0 ? [...item.starter_prompts] : ['']
  form.override_temperature = item.temperature !== null && item.temperature !== undefined
  form.temperature = item.temperature ?? 0.7
  form.is_enabled = item.is_enabled
  form.sort_order = item.sort_order
  dialogVisible.value = true
}

function addStarterRow() {
  if (form.starter_prompts.length >= 6) return
  form.starter_prompts.push('')
}

function removeStarterRow(idx: number) {
  form.starter_prompts.splice(idx, 1)
  if (form.starter_prompts.length === 0) {
    form.starter_prompts.push('')
  }
}

async function handleSave() {
  const code = form.code.trim()
  const name = form.name.trim()
  const prompt = form.system_prompt.trim()
  if (editingId.value === null && !/^[a-zA-Z0-9_-]{2,64}$/.test(code)) {
    ElMessage.warning('唯一编码需为 2~64 位字母、数字、下划线或连字符')
    return
  }
  if (!name) {
    ElMessage.warning('请输入智能体名称')
    return
  }
  if (prompt.length < 4) {
    ElMessage.warning('系统人设提示词至少需要 4 个字符')
    return
  }

  const starters = form.starter_prompts.map((s) => s.trim()).filter(Boolean)
    const payload: AIPersonaPayload = {
    ...(editingId.value === null ? { code } : {}),
    name,
    avatar_emoji: form.avatar_emoji.trim() || '💘',
    category: form.category,
    description: form.description.trim(),
    system_prompt: prompt,
    starter_prompts: starters,
    temperature: form.override_temperature ? form.temperature : null,
    clear_temperature: editingId.value !== null && !form.override_temperature,
    is_enabled: form.is_enabled,
    sort_order: form.sort_order,
  }

  submitting.value = true
  try {
    if (editingId.value === null) {
      await createAdminPersona(payload)
      ElMessage.success('智能体创建成功')
    } else {
      await updateAdminPersona(editingId.value, payload)
      ElMessage.success('智能体已更新')
    }
    dialogVisible.value = false
    await loadPersonas()
  } finally {
    submitting.value = false
  }
}

async function handleToggleEnabled(item: AIPersonaItem, enabled: boolean) {
  const prev = item.is_enabled
  item.is_enabled = enabled
  try {
    await updateAdminPersona(item.id, { is_enabled: enabled })
    ElMessage.success(enabled ? `已启用「${item.name}」` : `已停用「${item.name}」`)
  } catch {
    item.is_enabled = prev
  }
}

async function handleDelete(item: AIPersonaItem) {
  if (item.is_system) {
    ElMessage.info('系统预置智能体不可删除，您可以通过开关将其停用')
    return
  }
  try {
    await ElMessageBox.confirm(`确认删除自定义智能体「${item.name}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deleteAdminPersona(item.id)
  ElMessage.success('已删除智能体')
  await loadPersonas()
}

function tryInPlayground(item: AIPersonaItem) {
  void router.push({ path: '/ai-playground', query: { personaId: String(item.id) } })
}

onMounted(() => {
  void loadPersonas()
})
</script>

<template>
  <div v-loading="loading">
    <div class="page-header">
      <div>
        <h2 class="page-title">情感智能体工坊</h2>
        <p class="page-subtitle">
          专注恋爱情感场景：编排高情商话术、脱单约会、亲密关系与情绪疗愈人设模板，一键分发至对话工作台
        </p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" plain @click="loadPersonas">刷新</el-button>
        <el-button v-if="canManage" type="primary" :icon="Plus" @click="openCreateDialog">
          新建智能体
        </el-button>
      </div>
    </div>

    <div class="filter-bar page-card">
      <div class="category-tabs">
        <button
          v-for="cat in CATEGORY_OPTIONS"
          :key="cat.value"
          type="button"
          class="cat-pill"
          :class="{ 'is-active': activeCategory === cat.value }"
          @click="activeCategory = cat.value"
        >
          {{ cat.label }}
        </button>
      </div>
      <el-input
        v-model="keyword"
        placeholder="搜索智能体名称、编码或简介"
        :prefix-icon="Search"
        clearable
        class="search-input"
      />
    </div>

    <el-empty v-if="!loading && filteredList.length === 0" description="暂无匹配的智能体模板" />

    <el-row v-else :gutter="16">
      <el-col v-for="item in filteredList" :key="item.id" :xs="24" :sm="12" :lg="8">
        <div class="persona-card" :class="{ 'is-disabled': !item.is_enabled }">
          <div class="persona-top">
            <div class="persona-identity">
              <span class="emoji-badge">{{ item.avatar_emoji }}</span>
              <div class="identity-meta">
                <div class="name-row">
                  <span class="persona-name">{{ item.name }}</span>
                  <el-tag v-if="item.is_system" size="small" type="warning" effect="plain">
                    预置
                  </el-tag>
                  <el-tag v-else size="small" type="info" effect="plain">自定义</el-tag>
                </div>
                <div class="sub-tags">
                  <span class="cat-label">{{ CATEGORY_MAP[item.category] || item.category }}</span>
                  <span class="code-text mono-num">{{ item.code }}</span>
                </div>
              </div>
            </div>
            <el-switch
              v-if="canManage"
              :model-value="item.is_enabled"
              size="small"
              @change="(val: string | number | boolean) => handleToggleEnabled(item, Boolean(val))"
            />
            <el-tag v-else size="small" :type="item.is_enabled ? 'success' : 'info'">
              {{ item.is_enabled ? '启用' : '停用' }}
            </el-tag>
          </div>

          <p class="persona-desc">{{ item.description || '暂无简介描述' }}</p>

          <div class="prompt-preview">
            <span class="preview-label">System Prompt</span>
            <p class="preview-body">{{ item.system_prompt }}</p>
          </div>

          <div class="persona-metrics mono-num">
            <span>示例问题 {{ item.starter_prompts.length }} 条</span>
            <span>温度 {{ item.temperature !== null ? item.temperature : '继承默认' }}</span>
            <span>调用 {{ item.usage_count }} 次</span>
          </div>

          <div class="persona-actions">
            <el-button
              type="primary"
              plain
              size="small"
              :icon="ChatDotRound"
              :disabled="!item.is_enabled"
              @click="tryInPlayground(item)"
            >
              去对话试用
            </el-button>
            <div v-if="canManage" class="manage-btns">
              <el-button size="small" text :icon="EditPen" @click="openEditDialog(item)">
                编辑
              </el-button>
              <el-tooltip
                :content="item.is_system ? '系统预置智能体不可删除' : '删除智能体'"
                placement="top"
              >
                <span>
                  <el-button
                    size="small"
                    text
                    type="danger"
                    :icon="Delete"
                    :disabled="item.is_system"
                    @click="handleDelete(item)"
                  >
                    删除
                  </el-button>
                </span>
              </el-tooltip>
            </div>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建 AI 智能体' : '编辑 AI 智能体'"
      width="640px"
      destroy-on-close
    >
      <el-form label-width="112px" class="persona-form">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="唯一编码" required>
              <el-input
                v-model="form.code"
                :disabled="editingId !== null"
                placeholder="如: long_distance_coach"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="智能体名称" required>
              <el-input v-model="form.name" placeholder="展示名称" maxlength="64" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="图标 Emoji">
          <div class="emoji-picker-row">
            <el-input v-model="form.avatar_emoji" style="width: 72px" maxlength="8" />
            <button
              v-for="emoji in EMOJI_PRESETS"
              :key="emoji"
              type="button"
              class="emoji-opt"
              :class="{ 'is-picked': form.avatar_emoji === emoji }"
              @click="form.avatar_emoji = emoji"
            >
              {{ emoji }}
            </button>
          </div>
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="所属分类">
              <el-select v-model="form.category" style="width: 100%">
                <el-option
                  v-for="(label, key) in CATEGORY_MAP"
                  :key="key"
                  :label="label"
                  :value="key"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="排序权重">
              <el-input-number v-model="form.sort_order" :min="0" :max="9999" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="一句话简介">
          <el-input
            v-model="form.description"
            maxlength="255"
            placeholder="简洁描述该智能体的擅长领域与输出风格"
          />
        </el-form-item>

        <el-form-item label="系统提示词" required>
          <el-input
            v-model="form.system_prompt"
            type="textarea"
            :rows="4"
            maxlength="6000"
            show-word-limit
            placeholder="输入注入给大模型的 System Prompt 人设、约束和输出规范"
          />
        </el-form-item>

        <el-form-item label="覆盖温度">
          <div class="temp-row">
            <el-switch v-model="form.override_temperature" />
            <el-input-number
              v-if="form.override_temperature"
              v-model="form.temperature"
              :min="0"
              :max="2"
              :step="0.1"
              :precision="1"
            />
            <span class="temp-hint">
              {{ form.override_temperature ? '使用智能体专属采样温度' : '继承当前选中模型的默认温度' }}
            </span>
          </div>
        </el-form-item>

        <el-form-item label="快捷开场示例">
          <div class="starter-editor">
            <div v-for="(_item, idx) in form.starter_prompts" :key="idx" class="starter-row">
              <el-input
                v-model="form.starter_prompts[idx]"
                :placeholder="`示例问题 ${idx + 1}`"
                maxlength="200"
              />
              <el-button text type="danger" @click="removeStarterRow(idx)">移除</el-button>
            </div>
            <el-button
              v-if="form.starter_prompts.length < 6"
              size="small"
              plain
              :icon="Plus"
              @click="addStarterRow"
            >
              添加示例提问 ({{ form.starter_prompts.length }}/6)
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="启用状态">
          <el-switch v-model="form.is_enabled" active-text="立即开放使用" inactive-text="暂不启用" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSave">
          {{ editingId === null ? '确认创建' : '保存修改' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 18px;
  margin-bottom: 18px;
}

.category-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.cat-pill {
  border: 1px solid var(--ailove-border);
  background: var(--ailove-subtle);
  color: var(--ailove-ink-secondary);
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.18s;
}

.cat-pill:hover {
  border-color: var(--ailove-brand-200);
  color: var(--ailove-brand-600);
}

.cat-pill.is-active {
  background: var(--ailove-brand-600);
  border-color: var(--ailove-brand-600);
  color: #ffffff;
}

.search-input {
  width: 260px;
}

.persona-card {
  background: var(--ailove-surface);
  border: 1px solid var(--ailove-border);
  border-radius: var(--ailove-radius-lg);
  box-shadow: var(--ailove-shadow-card);
  padding: 18px;
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: transform 0.2s var(--ailove-ease), border-color 0.2s;
}

.persona-card:hover {
  transform: translateY(-2px);
  border-color: var(--ailove-brand-200);
}

.persona-card.is-disabled {
  opacity: 0.72;
}

.persona-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.persona-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.emoji-badge {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--ailove-brand-50);
  border: 1px solid var(--ailove-brand-200);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}

.identity-meta {
  min-width: 0;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.persona-name {
  font-size: 15.5px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.sub-tags {
  margin-top: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.cat-label {
  color: var(--ailove-brand-600);
  font-weight: 500;
}

.persona-desc {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--ailove-ink-secondary);
  min-height: 40px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.prompt-preview {
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
  border-radius: 10px;
  padding: 10px 12px;
}

.preview-label {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  color: var(--ailove-ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.preview-body {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ailove-ink-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.persona-metrics {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--ailove-ink-muted);
  padding-top: 2px;
}

.persona-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-top: 1px solid var(--ailove-border);
  padding-top: 12px;
}

.manage-btns {
  display: flex;
  align-items: center;
  gap: 4px;
}

.emoji-picker-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.emoji-opt {
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid var(--ailove-border);
  background: var(--ailove-subtle);
  font-size: 17px;
  cursor: pointer;
}

.emoji-opt.is-picked {
  border-color: var(--ailove-brand-500);
  background: var(--ailove-brand-50);
}

.temp-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.temp-hint {
  font-size: 12.5px;
  color: var(--ailove-ink-muted);
}

.starter-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.starter-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
