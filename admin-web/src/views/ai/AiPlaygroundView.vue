<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from '@/plugins/element-plus'
import { ChatDotRound, MagicStick, Postcard } from '@element-plus/icons-vue'
import {
  clearMyLoveProfile,
  createFavoriteReply,
  deleteAiConversation,
  deleteFavoriteReply,
  exportMyJournalFile,
  fetchAiConversations,
  fetchAvailableModels,
  fetchConversationMessages,
  fetchFavoriteReplies,
  fetchMyAiQuota,
  fetchMyLoveProfile,
  fetchPublicPersonas,
  fetchReplyHelperPresets,
  fetchSoftenDraftPresets,
  purgeMyAiData,
  renameAiConversation,
  saveMyLoveProfile,
  sendAiChat,
  sendReplyHelper,
  sendSoftenDraft,
  streamAiChat,
  streamReplyHelper,
  streamSoftenDraft,
  updateAiConversation,
  type AIConversationItem,
  type AIPersonaItem,
  type AIUserQuota,
  type AvailableAIModel,
  type EmotionCareNotice,
  type FavoriteCategory,
  type FavoriteReplyItem,
  type LoveProfilePresets,
  type RelationshipStage,
  type ReplyHelperPresets,
  type ReplyHelperScene,
  type ReplyHelperTone,
  type SoftenIntensity,
  type UserLoveProfile,
} from '@/api/ai'
import { decodeUtf8Base64, renderMarkdown } from '@/utils/markdown'
import { useMascotStore } from '@/stores/mascot'

interface ChatBubble {
  id: number
  role: 'user' | 'assistant'
  content: string
  reasoning?: string
  modelLabel?: string
  tokenUsage?: number
  loveProfileInjected?: boolean
  emotionCare?: EmotionCareNotice | null
  isError?: boolean
}

const WELCOME_MSG: ChatBubble = {
  id: 1,
  role: 'assistant',
  content:
    '你好！这里是 **AILOVE 恋爱情感 AI 对话工作台**，可在上方快速切换「高情商恋爱军师 / 心动约会策划师 / 亲密关系顾问 / 吵架降温调解员 / 深夜情绪树洞」等情感智能体，也支持自由直连对话。\n\n- 支持配置「**我的情感档案**」记忆卡，自动注入背景免去每次重复交代\n- 点击「**帮我回消息**」粘贴对方原话，一键拆解潜台词并生成 3 条高情商备选回复\n- 历史会话自动绑定情感智能体并支持置顶，低谷情绪自动触发温柔关怀护栏',
}

const DEFAULT_LOVE_PRESETS: LoveProfilePresets = {
  stages: [
    { code: 'single_crush', label: '暗恋观察期', emoji: '🌱' },
    { code: 'ambiguous', label: '暧昧升温期', emoji: '✨' },
    { code: 'in_love', label: '热恋甜蜜期', emoji: '💞' },
    { code: 'long_distance', label: '异地相处期', emoji: '🚄' },
    { code: 'cold_war', label: '争吵冷战修复', emoji: '🧊' },
    { code: 'breakup_healing', label: '失恋疗愈期', emoji: '🌙' },
    { code: 'married', label: '长期稳定/伴侣', emoji: '🏡' },
  ],
  partner_trait_presets: [
    '慢热型',
    '回避型依恋',
    '嘴硬心软',
    '工作忙回复慢',
    '细节控',
    '情绪敏感',
    '直球理性',
    '爱吃醋',
  ],
  my_trait_presets: [
    '容易内耗',
    '焦虑型依恋',
    '直球真诚',
    '不善表达',
    '容易心软',
    '注重仪式感',
  ],
}

const DEFAULT_REPLY_PRESETS: ReplyHelperPresets = {
  scenes: [
    { code: 'ambiguous', label: '暧昧升温', desc: '试探心意、自然拉近距离' },
    { code: 'cold_reply', label: '对方冷淡', desc: '回复敷衍、间隔变长怎么破局' },
    { code: 'conflict', label: '吵架哄人', desc: '情绪降温、体面化解僵局' },
    { code: 'date_invite', label: '约会邀约', desc: '发出或回应见面邀约' },
    { code: 'polite_decline', label: '体面婉拒', desc: '温和守边界、不伤和气' },
  ],
  tones: [
    { code: 'playful', label: '俏皮拉扯', desc: '轻幽默带点小反问，留出聊天钩子' },
    { code: 'gentle', label: '温柔体贴', desc: '先接住对方情绪，温暖有安全感' },
    { code: 'graceful', label: '体面台阶', desc: '不卑不亢，给彼此舒适退路' },
    { code: 'sincere', label: '真诚直球', desc: '坦荡清晰表达想法，减少猜忌内耗' },
    { code: 'humorous', label: '幽默破冰', desc: '轻松调侃化解尴尬或沉默' },
  ],
}

const route = useRoute()
const mascotStore = useMascotStore()

function syncMascotOutcome(assistantMsg: ChatBubble, happyTip: string) {
  mascotStore.setSpeaking(false)
  if (assistantMsg.emotionCare) {
    mascotStore.triggerComfort('恋恋给你抱抱，难过时先深呼吸一下~', 5400)
    return
  }
  if (!assistantMsg.isError && assistantMsg.content.trim()) {
    mascotStore.triggerHappy(happyTip, 2400)
  } else {
    mascotStore.setMood('idle')
  }
}

const availableModels = ref<AvailableAIModel[]>([])
const selectedConfigId = ref<number | undefined>(undefined)
const personas = ref<AIPersonaItem[]>([])
const selectedPersonaId = ref<number | undefined>(undefined)
const plazaDrawerVisible = ref(false)
const plazaCategory = ref('all')
const quota = ref<AIUserQuota | null>(null)
const conversations = ref<AIConversationItem[]>([])
const conversationsLoading = ref(false)
const sidebarVisible = ref(true)

// 情感背景记忆卡状态
const loveProfile = ref<UserLoveProfile | null>(null)
const lovePresets = ref<LoveProfilePresets>(DEFAULT_LOVE_PRESETS)
const loveProfileDrawerVisible = ref(false)
const loveProfileSaving = ref(false)
const customPartnerTrait = ref('')
const loveForm = reactive<{
  relationship_stage: RelationshipStage
  partner_nickname: string
  partner_traits: string[]
  my_traits: string[]
  relationship_goal: string
  communication_taboos: string
  background_notes: string
  auto_inject: boolean
}>({
  relationship_stage: '',
  partner_nickname: '',
  partner_traits: [],
  my_traits: [],
  relationship_goal: '',
  communication_taboos: '',
  background_notes: '',
  auto_inject: true,
})

// 「帮我回消息 2.0」结构化工具状态（支持微信截图识图）
const replyHelperVisible = ref(false)
const replyPresets = ref<ReplyHelperPresets>(DEFAULT_REPLY_PRESETS)
const replyImages = ref<string[]>([])
const replyFileInputRef = ref<HTMLInputElement | null>(null)
const replyForm = reactive<{
  partner_message: string
  scene: ReplyHelperScene
  tone: ReplyHelperTone
  context: string
  my_intent: string
}>({
  partner_message: '',
  scene: 'ambiguous',
  tone: 'playful',
  context: '',
  my_intent: '',
})

// 「先别发！」话术柔化器状态
const softenVisible = ref(false)
const softenIntensities = ref<Array<{ code: SoftenIntensity; label: string; desc: string }>>([
  { code: 'mild', label: '有点委屈', desc: '心里酸酸的，想温柔表达感受不被忽略' },
  { code: 'medium', label: '明显生气', desc: '有些火大或失望，想守住底线但不想翻脸' },
  { code: 'heated', label: '快上头了', desc: '差点把狠话/反话发出去，急需冷静降温' },
])
const softenForm = reactive<{
  draft_message: string
  intensity: SoftenIntensity
  context: string
}>({
  draft_message: '',
  intensity: 'heated',
  context: '',
})

// 无痕倾诉模式 & 话术收藏夹 & 个人数据主权
const incognitoMode = ref(false)
const favoritesDrawerVisible = ref(false)
const favoritesLoading = ref(false)
const favoriteItems = ref<FavoriteReplyItem[]>([])
const favoriteFilter = ref('all')
const newFavContent = ref('')
const newFavNote = ref('')
const exportingJournal = ref(false)
const purgingData = ref(false)

const sessionId = ref('')
const inputText = ref('')
const systemPrompt = ref('')
const useStream = ref(true)
const sending = ref(false)
const loadingHistory = ref(false)
let abortController: AbortController | null = null

const messages = ref<ChatBubble[]>([{ ...WELCOME_MSG }])
const listRef = ref<HTMLElement | null>(null)

const currentModel = computed(
  () => availableModels.value.find((m) => m.id === selectedConfigId.value) ?? null,
)

const activePersona = computed(
  () => personas.value.find((p) => p.id === selectedPersonaId.value) ?? null,
)

const loveProfileActive = computed(
  () => Boolean(loveProfile.value?.is_configured && loveProfile.value?.auto_inject),
)

const loveProfileBadgeText = computed(() => {
  const lp = loveProfile.value
  if (!lp?.is_configured) return '情感档案'
  const stage = lp.relationship_stage_label || '已填写'
  return lp.auto_inject ? `${stage} · 记忆生效` : `${stage} · 已暂停`
})

const plazaFilteredPersonas = computed(() =>
  plazaCategory.value === 'all'
    ? personas.value
    : personas.value.filter((p) => p.category === plazaCategory.value),
)

const quotaSummaryText = computed(() => {
  const q = quota.value
  if (!q) return ''
  if (q.is_exempt) {
    return `配额豁免 · 今日 ${q.requests_used} 次`
  }
  if (q.requests_limit > 0) {
    return `今日剩余 ${q.requests_remaining ?? 0}/${q.requests_limit} 次`
  }
  return `今日已用 ${q.requests_used} 次`
})

const lastAssistantIdx = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i]?.role === 'assistant') return i
  }
  return -1
})

function resolvePersonaEmoji(personaId?: number | null): string {
  if (!personaId) return '💬'
  return personas.value.find((p) => p.id === personaId)?.avatar_emoji || '💘'
}

function syncLoveFormFromProfile(lp: UserLoveProfile) {
  loveForm.relationship_stage = lp.relationship_stage || ''
  loveForm.partner_nickname = lp.partner_nickname || ''
  loveForm.partner_traits = [...(lp.partner_traits || [])]
  loveForm.my_traits = [...(lp.my_traits || [])]
  loveForm.relationship_goal = lp.relationship_goal || ''
  loveForm.communication_taboos = lp.communication_taboos || ''
  loveForm.background_notes = lp.background_notes || ''
  loveForm.auto_inject = lp.auto_inject !== false
}

async function loadLoveProfile() {
  try {
    const res = await fetchMyLoveProfile()
    loveProfile.value = res.profile
    if (res.presets?.stages?.length) {
      lovePresets.value = res.presets
    }
    syncLoveFormFromProfile(res.profile)
  } catch {
    // 忽略
  }
}

async function loadReplyPresets() {
  try {
    const [res, softenRes] = await Promise.all([
      fetchReplyHelperPresets(),
      fetchSoftenDraftPresets().catch(() => null),
    ])
    if (res.scenes?.length && res.tones?.length) {
      replyPresets.value = res
    }
    if (softenRes?.intensities?.length) {
      softenIntensities.value = softenRes.intensities
    }
  } catch {
    // 使用内置默认值
  }
}

async function loadFavorites() {
  favoritesLoading.value = true
  try {
    const res = await fetchFavoriteReplies(favoriteFilter.value)
    favoriteItems.value = res.items
  } catch {
    // 忽略
  } finally {
    favoritesLoading.value = false
  }
}

function openFavoritesDrawer() {
  favoritesDrawerVisible.value = true
  void loadFavorites()
}

function extractFirstQuoteOrFull(text: string): string {
  const lines = (text || '').split('\n')
  for (const raw of lines) {
    const trimmed = raw.trim()
    if (trimmed.startsWith('>')) {
      const cleaned = trimmed.replace(/^>+\s*/, '').replace(/^["「『]+|["」』]+$/g, '').trim()
      if (cleaned.length >= 4) return cleaned
    }
  }
  return (text || '').trim().slice(0, 600)
}

async function handleFavoriteBubble(msg: ChatBubble) {
  const snippet = extractFirstQuoteOrFull(msg.content)
  if (!snippet) return
  try {
    const cat: FavoriteCategory = msg.modelLabel?.includes('调解')
      ? 'soften'
      : msg.modelLabel?.includes('军师')
        ? 'reply_helper'
        : 'chat'
    const res = await createFavoriteReply({
      content: snippet,
      category: cat,
      scene_label: msg.modelLabel?.split('(')[0]?.trim() || 'AI 对话',
    })
    mascotStore.triggerHappy('帮你在高情商话术库藏好啦 ✨', 2400)
    ElMessage.success(res.deduplicated ? '已在收藏夹中' : '已收藏到高情商话术库')
  } catch {
    // 忽略
  }
}

async function handleAddManualFavorite() {
  const content = newFavContent.value.trim()
  if (!content) {
    ElMessage.warning('请输入要收藏的话术')
    return
  }
  await createFavoriteReply({
    content,
    category: 'custom',
    scene_label: '自定义备忘',
    note: newFavNote.value.trim(),
  })
  newFavContent.value = ''
  newFavNote.value = ''
  ElMessage.success('已保存到话术收藏夹')
  await loadFavorites()
}

async function handleDeleteFavorite(id: number) {
  await deleteFavoriteReply(id)
  ElMessage.success('已移出收藏夹')
  await loadFavorites()
}

async function handleExportMyJournal() {
  exportingJournal.value = true
  try {
    const fname = await exportMyJournalFile()
    ElMessage.success(`已导出私密情感手账：${fname}`)
  } finally {
    exportingJournal.value = false
  }
}

async function handlePurgeAllMyData() {
  try {
    await ElMessageBox.confirm(
      '将彻底删除你账号下的全部云端历史会话、情感档案记忆卡与话术收藏，不可恢复！确认继续？',
      '彻底清除个人数据',
      { confirmButtonText: '确认彻底清除', cancelButtonText: '取消', type: 'warning' },
    )
    purgingData.value = true
    await purgeMyAiData(true, true)
    handleNewConversation()
    await Promise.all([loadConversations(), loadLoveProfile()])
    ElMessage.success('你的全部云端私密情感数据已彻底清空')
  } catch {
    // 取消
  } finally {
    purgingData.value = false
  }
}

function compressImageToDataUrl(file: File, maxDim = 1280): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('读取图片失败'))
    reader.onload = () => {
      const img = new Image()
      img.onerror = () => reject(new Error('解析图片失败'))
      img.onload = () => {
        const scale = Math.min(1, maxDim / Math.max(img.width, img.height))
        const w = Math.max(1, Math.round(img.width * scale))
        const h = Math.max(1, Math.round(img.height * scale))
        const canvas = document.createElement('canvas')
        canvas.width = w
        canvas.height = h
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          resolve(String(reader.result || ''))
          return
        }
        ctx.drawImage(img, 0, 0, w, h)
        resolve(canvas.toDataURL('image/jpeg', 0.82))
      }
      img.src = String(reader.result || '')
    }
    reader.readAsDataURL(file)
  })
}

async function handleReplyImageChange(evt: Event) {
  const input = evt.target as HTMLInputElement | null
  const files = Array.from(input?.files || [])
  if (!files.length) return
  const remain = Math.max(0, 3 - replyImages.value.length)
  for (const file of files.slice(0, remain)) {
    try {
      const dataUrl = await compressImageToDataUrl(file)
      replyImages.value.push(dataUrl)
    } catch {
      ElMessage.warning(`截图 ${file.name} 处理失败`)
    }
  }
  if (input) input.value = ''
}

function removeReplyImage(idx: number) {
  replyImages.value.splice(idx, 1)
}

function openLoveProfileDrawer() {
  if (loveProfile.value) {
    syncLoveFormFromProfile(loveProfile.value)
  }
  loveProfileDrawerVisible.value = true
}

function toggleTraitTag(list: string[], tag: string) {
  const idx = list.indexOf(tag)
  if (idx >= 0) {
    list.splice(idx, 1)
  } else if (list.length < 8) {
    list.push(tag)
  } else {
    ElMessage.warning('最多选择 8 个标签')
  }
}

function addCustomPartnerTrait() {
  const val = customPartnerTrait.value.trim()
  if (!val) return
  if (loveForm.partner_traits.includes(val)) {
    customPartnerTrait.value = ''
    return
  }
  if (loveForm.partner_traits.length >= 8) {
    ElMessage.warning('对方标签最多添加 8 个')
    return
  }
  loveForm.partner_traits.push(val.slice(0, 24))
  customPartnerTrait.value = ''
}

async function handleSaveLoveProfile() {
  loveProfileSaving.value = true
  try {
    const res = await saveMyLoveProfile({
      relationship_stage: loveForm.relationship_stage,
      partner_nickname: loveForm.partner_nickname.trim(),
      partner_traits: [...loveForm.partner_traits],
      my_traits: [...loveForm.my_traits],
      relationship_goal: loveForm.relationship_goal.trim(),
      communication_taboos: loveForm.communication_taboos.trim(),
      background_notes: loveForm.background_notes.trim(),
      auto_inject: loveForm.auto_inject,
    })
    loveProfile.value = res.profile
    syncLoveFormFromProfile(res.profile)
    loveProfileDrawerVisible.value = false
    ElMessage.success(
      res.profile.is_configured && res.profile.auto_inject
        ? '情感档案已保存，后续对话将自动结合你的背景'
        : '情感档案已保存',
    )
  } finally {
    loveProfileSaving.value = false
  }
}

async function handleClearLoveProfile() {
  try {
    await ElMessageBox.confirm('确认清空个人情感档案记忆卡？清空后可随时重新填写。', '清空档案', {
      confirmButtonText: '确认清空',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const res = await clearMyLoveProfile()
    loveProfile.value = res.profile
    syncLoveFormFromProfile(res.profile)
    ElMessage.success('个人情感档案已清空')
  } catch {
    // 取消
  }
}

async function loadModels() {
  try {
    const res = await fetchAvailableModels()
    availableModels.value = res.items
    const def = res.items.find((m) => m.is_default) ?? res.items[0]
    if (def && selectedConfigId.value === undefined) {
      selectedConfigId.value = def.id
    }
  } catch {
    // 忽略
  }
}

async function loadPersonas() {
  try {
    const res = await fetchPublicPersonas()
    personas.value = res.items
    const qPid = Number(route.query.personaId)
    if (Number.isFinite(qPid) && qPid > 0) {
      const matched = res.items.find((p) => p.id === qPid)
      if (matched) {
        selectedPersonaId.value = matched.id
      }
    }
  } catch {
    // 忽略
  }
}

async function loadQuota() {
  try {
    quota.value = await fetchMyAiQuota()
  } catch {
    // 忽略
  }
}

function selectPersona(pid?: number) {
  selectedPersonaId.value = pid
  plazaDrawerVisible.value = false
}

async function quickAskStarter(promptText: string) {
  if (!promptText || sending.value) return
  await sendPromptText(promptText, true)
}

async function loadConversations() {
  conversationsLoading.value = true
  try {
    const res = await fetchAiConversations()
    conversations.value = res.items
  } catch {
    // 忽略
  } finally {
    conversationsLoading.value = false
  }
}

async function selectConversation(conv: AIConversationItem) {
  if (sending.value) return
  loadingHistory.value = true
  try {
    const detail = await fetchConversationMessages(conv.session_id)
    sessionId.value = detail.session_id
    // 自动还原该历史会话所绑定的情感智能体人设
    if (detail.persona_id && personas.value.some((p) => p.id === detail.persona_id)) {
      selectedPersonaId.value = detail.persona_id
    } else {
      selectedPersonaId.value = undefined
    }
    const labelPrefix = detail.persona_name ? `${detail.persona_name} · ` : ''
    messages.value = detail.messages
      .filter((m) => m.role === 'user' || m.role === 'assistant')
      .map((m, idx) => ({
        id: m.id ?? idx + 1,
        role: m.role as 'user' | 'assistant',
        content: m.content,
        modelLabel: m.role === 'assistant' ? `${labelPrefix}${detail.model_name || 'AI'}` : undefined,
        tokenUsage: m.token_usage || undefined,
      }))
    if (messages.value.length === 0) {
      messages.value = [{ ...WELCOME_MSG }]
    }
    await scrollToBottom()
  } finally {
    loadingHistory.value = false
  }
}

function handleNewConversation() {
  if (sending.value) {
    abortController?.abort()
  }
  sessionId.value = ''
  messages.value = [
    {
      id: Date.now(),
      role: 'assistant',
      content: '已开启全新会话，请输入你想探讨的情感话题，或点击「帮我回消息」直接粘贴 TA 的原话。',
    },
  ]
}

async function handleTogglePin(conv: AIConversationItem) {
  const nextPinned = !conv.is_pinned
  try {
    await updateAiConversation(conv.session_id, { is_pinned: nextPinned })
    ElMessage.success(nextPinned ? '会话已置顶' : '已取消置顶')
    await loadConversations()
  } catch {
    // 忽略
  }
}

async function handleRenameConversation(conv: AIConversationItem) {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话标题', '重命名会话', {
      inputValue: conv.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPattern: /^.{1,120}$/,
      inputErrorMessage: '标题长度须为 1~120 字符',
    })
    const res = await renameAiConversation(conv.session_id, value)
    conv.title = res.title
    ElMessage.success('会话标题已更新')
  } catch {
    // 取消
  }
}

async function handleDeleteConversation(conv: AIConversationItem) {
  try {
    await ElMessageBox.confirm(`确认删除历史会话「${conv.title}」？删除后不可恢复。`, '删除确认', {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await deleteAiConversation(conv.session_id)
    ElMessage.success('会话已删除')
    if (sessionId.value === conv.session_id) {
      handleNewConversation()
    }
    await loadConversations()
  } catch {
    // 取消
  }
}

async function scrollToBottom() {
  await nextTick()
  if (listRef.value) {
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
}

async function sendPromptText(text: string, appendUserBubble = true) {
  if (!text || sending.value) return
  sending.value = true
  mascotStore.setMood('thinking')
  mascotStore.setSpeaking(false)

  if (appendUserBubble) {
    messages.value.push({ id: Date.now(), role: 'user', content: text })
  }
  const assistantMsg: ChatBubble = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    reasoning: '',
    modelLabel: currentModel.value
      ? `${currentModel.value.name} (${currentModel.value.model_name})`
      : 'AILOVE Assistant',
  }
  messages.value.push(assistantMsg)
  await scrollToBottom()

  try {
    const clientTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
    const ephemeralHist = incognitoMode.value
      ? messages.value
          .slice(1, -1)
          .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content && !m.isError)
          .slice(-12)
          .map((m) => ({ role: m.role, content: m.content }))
      : undefined
    const payload = {
      message: text,
      session_id: sessionId.value || undefined,
      config_id: selectedConfigId.value,
      persona_id: selectedPersonaId.value,
      system_prompt: systemPrompt.value.trim() || undefined,
      timezone: clientTz,
      incognito: incognitoMode.value,
      ephemeral_history: ephemeralHist,
    }

    if (useStream.value) {
      abortController = new AbortController()
      await streamAiChat(
        payload,
        {
          onMeta: (meta) => {
            sessionId.value = meta.session_id
            assistantMsg.loveProfileInjected = Boolean(meta.love_profile_injected)
            assistantMsg.emotionCare = meta.emotion_care ?? null
            if (meta.emotion_care) {
              mascotStore.triggerComfort('恋恋给你抱抱，难过时先深呼吸一下~', 5400)
            }
            if (meta.model) {
              const pPrefix = meta.persona_name ? `${meta.persona_name} · ` : ''
              assistantMsg.modelLabel = `${pPrefix}${meta.config_name || 'AI'} (${meta.model})${meta.is_mock ? ' · 演示' : ''}`
            }
          },
          onFallback: (backupLabel) => {
            assistantMsg.modelLabel = `${backupLabel} · 自动容灾接管`
          },
          onReasoning: (chunk) => {
            assistantMsg.reasoning = (assistantMsg.reasoning || '') + chunk
            void scrollToBottom()
          },
          onDelta: (chunk) => {
            if (!assistantMsg.emotionCare) mascotStore.setSpeaking(true)
            assistantMsg.content += chunk
            void scrollToBottom()
          },
          onUsage: (total) => {
            assistantMsg.tokenUsage = total
          },
          onError: (errMsg) => {
            assistantMsg.isError = true
            assistantMsg.content = assistantMsg.content
              ? `${assistantMsg.content}\n\n⚠️ ${errMsg}`
              : `⚠️ ${errMsg}`
          },
        },
        abortController.signal,
      )
    } else {
      const res = await sendAiChat(payload)
      sessionId.value = res.session_id
      assistantMsg.reasoning = res.reasoning || ''
      assistantMsg.content = res.reply
      assistantMsg.tokenUsage = res.token_usage || undefined
      assistantMsg.loveProfileInjected = Boolean(res.love_profile_injected)
      assistantMsg.emotionCare = res.emotion_care ?? null
      const pPrefix = res.persona_name ? `${res.persona_name} · ` : ''
      const fbSuffix = res.fallback_used ? ' · 自动容灾接管' : ''
      assistantMsg.modelLabel = `${pPrefix}${res.config_name || 'AI'} (${res.model})${res.is_mock ? ' · 演示' : ''}${fbSuffix}`
      await scrollToBottom()
    }
    syncMascotOutcome(assistantMsg, '灵感分析好啦，快看看合适哪一句 ✨')
    void Promise.all([loadConversations(), loadQuota()])
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      assistantMsg.content = assistantMsg.content
        ? `${assistantMsg.content}\n\n（已停止生成）`
        : '（已停止生成）'
    } else {
      assistantMsg.isError = true
      assistantMsg.content = `请求出错：${err instanceof Error ? err.message : '未知错误'}`
    }
  } finally {
    abortController = null
    sending.value = false
    mascotStore.setSpeaking(false)
  }
}

async function handleSubmitReplyHelper() {
  const partnerMsg = replyForm.partner_message.trim()
  const imgs = [...replyImages.value]
  if (!partnerMsg && imgs.length === 0) {
    ElMessage.warning('请粘贴对方原话或至少上传 1 张聊天截图')
    return
  }
  if (sending.value) return

  const sceneLabel =
    replyPresets.value.scenes.find((s) => s.code === replyForm.scene)?.label || replyForm.scene
  const toneLabel =
    replyPresets.value.tones.find((t) => t.code === replyForm.tone)?.label || replyForm.tone

  const previewLines = [`【帮我回消息 · ${sceneLabel} / ${toneLabel}】`]
  if (imgs.length > 0) previewLines.push(`[已附 ${imgs.length} 张微信聊天截图]`)
  if (partnerMsg) previewLines.push(`对方原话：「${partnerMsg}」`)
  if (replyForm.my_intent.trim()) {
    previewLines.push(`我想表达：${replyForm.my_intent.trim()}`)
  }

  replyHelperVisible.value = false
  sending.value = true
  mascotStore.setMood('thinking')
  mascotStore.setSpeaking(false)

  const userBubble: ChatBubble = {
    id: Date.now(),
    role: 'user',
    content: previewLines.join('\n'),
  }
  const assistantMsg: ChatBubble = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    reasoning: '',
    modelLabel: imgs.length > 0 ? '视觉识图军师 · 读图中...' : '高情商恋爱军师 · 拆解中...',
  }
  messages.value.push(userBubble, assistantMsg)
  await scrollToBottom()

  try {
    const clientTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
    const payload = {
      partner_message: partnerMsg,
      images: imgs,
      scene: replyForm.scene,
      tone: replyForm.tone,
      context: replyForm.context.trim(),
      my_intent: replyForm.my_intent.trim(),
      session_id: sessionId.value || undefined,
      config_id: selectedConfigId.value,
      persona_id: selectedPersonaId.value,
      timezone: clientTz,
      incognito: incognitoMode.value,
    }

    if (useStream.value) {
      abortController = new AbortController()
      await streamReplyHelper(
        payload,
        {
          onMeta: (meta) => {
            sessionId.value = meta.session_id
            if (meta.persona_id) {
              selectedPersonaId.value = meta.persona_id
            }
            if (meta.prompt_preview) {
              userBubble.content = meta.prompt_preview
            }
            assistantMsg.loveProfileInjected = Boolean(meta.love_profile_injected)
            assistantMsg.emotionCare = meta.emotion_care ?? null
            if (meta.emotion_care) {
              mascotStore.triggerComfort('恋恋给你抱抱，难过时先深呼吸一下~', 5400)
            }
            if (meta.model) {
              const pPrefix = meta.persona_name ? `${meta.persona_name} · ` : ''
              assistantMsg.modelLabel = `${pPrefix}${meta.config_name || 'AI'} (${meta.model})${meta.is_mock ? ' · 演示' : ''}`
            }
          },
          onFallback: (backupLabel) => {
            assistantMsg.modelLabel = `${backupLabel} · 自动容灾接管`
          },
          onReasoning: (chunk) => {
            assistantMsg.reasoning = (assistantMsg.reasoning || '') + chunk
            void scrollToBottom()
          },
          onDelta: (chunk) => {
            if (!assistantMsg.emotionCare) mascotStore.setSpeaking(true)
            assistantMsg.content += chunk
            void scrollToBottom()
          },
          onUsage: (total) => {
            assistantMsg.tokenUsage = total
          },
          onError: (errMsg) => {
            assistantMsg.isError = true
            assistantMsg.content = assistantMsg.content
              ? `${assistantMsg.content}\n\n⚠️ ${errMsg}`
              : `⚠️ ${errMsg}`
          },
        },
        abortController.signal,
      )
    } else {
      const res = await sendReplyHelper(payload)
      sessionId.value = res.session_id
      if (res.persona_id) {
        selectedPersonaId.value = res.persona_id
      }
      assistantMsg.reasoning = res.reasoning || ''
      assistantMsg.content = res.reply
      assistantMsg.tokenUsage = res.token_usage || undefined
      assistantMsg.loveProfileInjected = Boolean(res.love_profile_injected)
      assistantMsg.emotionCare = res.emotion_care ?? null
      const pPrefix = res.persona_name ? `${res.persona_name} · ` : ''
      const fbSuffix = res.fallback_used ? ' · 自动容灾接管' : ''
      assistantMsg.modelLabel = `${pPrefix}${res.config_name || 'AI'} (${res.model})${res.is_mock ? ' · 演示' : ''}${fbSuffix}`
      await scrollToBottom()
    }
    replyForm.partner_message = ''
    replyForm.context = ''
    replyForm.my_intent = ''
    replyImages.value = []
    syncMascotOutcome(assistantMsg, '高情商回复备选好啦，挑一条最合心意的 ✨')
    void Promise.all([loadConversations(), loadQuota()])
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      assistantMsg.content = assistantMsg.content
        ? `${assistantMsg.content}\n\n（已停止生成）`
        : '（已停止生成）'
    } else {
      assistantMsg.isError = true
      assistantMsg.content = `请求出错：${err instanceof Error ? err.message : '未知错误'}`
    }
  } finally {
    abortController = null
    sending.value = false
    mascotStore.setSpeaking(false)
  }
}

async function handleSubmitSoftenDraft() {
  const draftMsg = softenForm.draft_message.trim()
  if (!draftMsg) {
    ElMessage.warning('请先粘贴你打算发出去但怕伤人的草稿')
    return
  }
  if (sending.value) return

  const lvLabel =
    softenIntensities.value.find((i) => i.code === softenForm.intensity)?.label ||
    softenForm.intensity
  softenVisible.value = false
  sending.value = true
  mascotStore.setMood('thinking')
  mascotStore.setSpeaking(false)

  const userBubble: ChatBubble = {
    id: Date.now(),
    role: 'user',
    content: `【先别发！话术柔化 · ${lvLabel}】\n原话草稿：「${draftMsg}」`,
  }
  const assistantMsg: ChatBubble = {
    id: Date.now() + 1,
    role: 'assistant',
    content: '',
    reasoning: '',
    modelLabel: '吵架降温调解员 · 降温改写中...',
  }
  messages.value.push(userBubble, assistantMsg)
  await scrollToBottom()

  try {
    const clientTz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai'
    const payload = {
      draft_message: draftMsg,
      intensity: softenForm.intensity,
      context: softenForm.context.trim(),
      session_id: sessionId.value || undefined,
      config_id: selectedConfigId.value,
      persona_id: selectedPersonaId.value,
      timezone: clientTz,
      incognito: incognitoMode.value,
    }
    if (useStream.value) {
      abortController = new AbortController()
      await streamSoftenDraft(
        payload,
        {
          onMeta: (meta) => {
            sessionId.value = meta.session_id
            if (meta.persona_id) selectedPersonaId.value = meta.persona_id
            if (meta.prompt_preview) userBubble.content = meta.prompt_preview
            assistantMsg.loveProfileInjected = Boolean(meta.love_profile_injected)
            assistantMsg.emotionCare = meta.emotion_care ?? null
            if (meta.emotion_care) {
              mascotStore.triggerComfort('先深呼吸，恋恋陪你把话揉软再发出~', 5400)
            }
            if (meta.model) {
              const pPrefix = meta.persona_name ? `${meta.persona_name} · ` : ''
              assistantMsg.modelLabel = `${pPrefix}${meta.config_name || 'AI'} (${meta.model})${meta.is_mock ? ' · 演示' : ''}`
            }
          },
          onFallback: (backupLabel) => {
            assistantMsg.modelLabel = `${backupLabel} · 自动容灾接管`
          },
          onReasoning: (chunk) => {
            assistantMsg.reasoning = (assistantMsg.reasoning || '') + chunk
            void scrollToBottom()
          },
          onDelta: (chunk) => {
            if (!assistantMsg.emotionCare) mascotStore.setSpeaking(true)
            assistantMsg.content += chunk
            void scrollToBottom()
          },
          onUsage: (total) => {
            assistantMsg.tokenUsage = total
          },
          onError: (errMsg) => {
            assistantMsg.isError = true
            assistantMsg.content = assistantMsg.content
              ? `${assistantMsg.content}\n\n⚠️ ${errMsg}`
              : `⚠️ ${errMsg}`
          },
        },
        abortController.signal,
      )
    } else {
      const res = await sendSoftenDraft(payload)
      sessionId.value = res.session_id
      if (res.persona_id) selectedPersonaId.value = res.persona_id
      assistantMsg.reasoning = res.reasoning || ''
      assistantMsg.content = res.reply
      assistantMsg.tokenUsage = res.token_usage || undefined
      assistantMsg.loveProfileInjected = Boolean(res.love_profile_injected)
      assistantMsg.emotionCare = res.emotion_care ?? null
      const pPrefix = res.persona_name ? `${res.persona_name} · ` : ''
      const fbSuffix = res.fallback_used ? ' · 自动容灾接管' : ''
      assistantMsg.modelLabel = `${pPrefix}${res.config_name || 'AI'} (${res.model})${res.is_mock ? ' · 演示' : ''}${fbSuffix}`
      await scrollToBottom()
    }
    softenForm.draft_message = ''
    softenForm.context = ''
    syncMascotOutcome(assistantMsg, '先深呼吸，改好温和表达啦 💙')
    void Promise.all([loadConversations(), loadQuota()])
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      assistantMsg.content = assistantMsg.content
        ? `${assistantMsg.content}\n\n（已停止生成）`
        : '（已停止生成）'
    } else {
      assistantMsg.isError = true
      assistantMsg.content = `请求出错：${err instanceof Error ? err.message : '未知错误'}`
    }
  } finally {
    abortController = null
    sending.value = false
    mascotStore.setSpeaking(false)
  }
}

async function handleSend() {
  const text = inputText.value.trim()
  if (!text || sending.value) return
  inputText.value = ''
  await sendPromptText(text, true)
}

async function handleRegenerate() {
  if (sending.value) return
  let lastUserText = ''
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const item = messages.value[i]
    if (item?.role === 'user') {
      lastUserText = item.content
      break
    }
  }
  if (!lastUserText) return
  if (lastAssistantIdx.value >= 0) {
    messages.value.splice(lastAssistantIdx.value, 1)
  }
  await sendPromptText(lastUserText, false)
}

function handleStop() {
  abortController?.abort()
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('当前浏览器环境不支持自动写入剪贴板')
  }
}

function handleMessageAreaClick(event: MouseEvent) {
  const target = event.target as HTMLElement | null
  const btn = target?.closest('.md-copy-btn') as HTMLButtonElement | null
  if (!btn) return
  const b64 = btn.getAttribute('data-copy-b64') || ''
  const code = decodeUtf8Base64(b64)
  if (code) {
    void copyText(code).then(() => {
      btn.textContent = '已复制'
      setTimeout(() => {
        btn.textContent = '复制代码'
      }, 1500)
    })
  }
}

onMounted(async () => {
  await Promise.all([
    loadModels(),
    loadPersonas(),
    loadConversations(),
    loadQuota(),
    loadLoveProfile(),
    loadReplyPresets(),
  ])
  const qSid = typeof route.query.session_id === 'string' ? route.query.session_id.trim() : ''
  if (qSid) {
    await selectConversation({ session_id: qSid } as AIConversationItem)
  }
})

onBeforeUnmount(() => {
  abortController?.abort()
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2 class="page-title">LangChain AI 工作台</h2>
        <p class="page-subtitle">
          持久化多会话管理 + Markdown 代码高亮排版，实时切换 DeepSeek 双协议引擎与思考链流
        </p>
      </div>
      <div class="toolbar-actions">
        <el-tag
          v-if="quota"
          :type="quota.is_exempt ? 'warning' : (quota.requests_remaining ?? 1) <= 5 ? 'danger' : 'info'"
          effect="plain"
          class="mono-num quota-pill"
        >
          {{ quotaSummaryText }}
        </el-tag>
        <el-button
          :type="loveProfileActive ? 'primary' : 'default'"
          plain
          size="small"
          :icon="Postcard"
          @click="openLoveProfileDrawer"
        >
          {{ loveProfileBadgeText }}
        </el-button>
        <el-button plain size="small" :icon="ChatDotRound" @click="replyHelperVisible = true">
          帮我回消息
        </el-button>
        <el-button plain size="small" @click="softenVisible = true">🧊 先别发</el-button>
        <el-button plain size="small" @click="openFavoritesDrawer">⭐ 话术库</el-button>
        <el-button
          :type="incognitoMode ? 'warning' : 'default'"
          plain
          size="small"
          @click="incognitoMode = !incognitoMode"
        >
          {{ incognitoMode ? '🕵️ 无痕已开' : '🕵️ 无痕倾诉' }}
        </el-button>
        <el-button plain size="small" :icon="MagicStick" @click="plazaDrawerVisible = true">
          智能体广场
        </el-button>
        <el-button plain size="small" @click="sidebarVisible = !sidebarVisible">
          {{ sidebarVisible ? '收起历史栏' : '展开历史栏' }}
        </el-button>
        <el-select
          v-model="selectedConfigId"
          placeholder="选择模型配置"
          style="width: 240px"
        >
          <el-option
            v-for="m in availableModels"
            :key="m.id"
            :label="`${m.name} (${m.model_name})`"
            :value="m.id"
          >
            <div class="model-opt">
              <span>{{ m.name }}</span>
              <el-tag
                size="small"
                :type="m.has_api_key ? 'success' : 'warning'"
                effect="plain"
              >
                {{ m.has_api_key ? `${m.model_name} · ${m.protocol}` : '未填Key' }}
              </el-tag>
            </div>
          </el-option>
        </el-select>
        <el-switch v-model="useStream" active-text="SSE 流式" inactive-text="同步" />
        <el-button type="primary" plain icon="Plus" @click="handleNewConversation">新建对话</el-button>
      </div>
    </div>

    <div class="workbench-shell">
      <!-- 左侧历史会话栏 -->
      <aside v-show="sidebarVisible" v-loading="conversationsLoading" class="page-card history-pane">
        <div class="history-head">
          <span>历史会话 ({{ conversations.length }})</span>
          <el-button link type="primary" size="small" icon="Refresh" @click="loadConversations" />
        </div>
        <div v-if="conversations.length === 0" class="history-empty">
          暂无历史会话，发起第一轮对话后将自动持久保存
        </div>
        <div v-else class="history-list">
          <div
            v-for="conv in conversations"
            :key="conv.session_id"
            class="history-item"
            :class="{ 'is-active': sessionId === conv.session_id, 'is-pinned': conv.is_pinned }"
            @click="selectConversation(conv)"
          >
            <div class="history-title-row">
              <span v-if="conv.is_pinned" class="pin-mark" title="已置顶">📌</span>
              <span class="history-title" :title="conv.title">{{ conv.title }}</span>
            </div>
            <div v-if="conv.persona_name" class="history-persona-badge">
              <span>{{ resolvePersonaEmoji(conv.persona_id) }}</span>
              <span>{{ conv.persona_name }}</span>
            </div>
            <div class="history-meta">
              <span class="mono-num history-model">{{ conv.model_name || 'AI' }}</span>
              <span class="history-ops" @click.stop>
                <el-button
                  link
                  size="small"
                  :type="conv.is_pinned ? 'warning' : 'info'"
                  :title="conv.is_pinned ? '取消置顶' : '置顶会话'"
                  @click="handleTogglePin(conv)"
                >
                  {{ conv.is_pinned ? '取消' : '置顶' }}
                </el-button>
                <el-button
                  link
                  size="small"
                  type="primary"
                  @click="handleRenameConversation(conv)"
                >
                  改名
                </el-button>
                <el-button
                  link
                  size="small"
                  type="danger"
                  @click="handleDeleteConversation(conv)"
                >
                  删
                </el-button>
              </span>
            </div>
          </div>
        </div>
        <div class="history-foot-ops">
          <el-button size="small" plain :loading="exportingJournal" @click="handleExportMyJournal">
            导出手账 .md
          </el-button>
          <el-button size="small" type="danger" plain :loading="purgingData" @click="handlePurgeAllMyData">
            清空个人数据
          </el-button>
        </div>
      </aside>

      <!-- 右侧对话主工作台 -->
      <div v-loading="loadingHistory" class="page-card playground-card">
        <div v-if="incognitoMode" class="incognito-banner">
          🕵️ 已开启「无痕倾诉」模式：本轮对话仅保留在当前页面，绝不保存云端记录或计入导出手账。
        </div>
        <div class="prompt-row">
          <el-input
            v-model="systemPrompt"
            :placeholder="
              activePersona
                ? `已激活「${activePersona.name}」人设（留空自动生效，输入可临时覆盖）`
                : '可选：临时覆盖 System Prompt（留空自动采用所选模型配置中的默认人设）'
            "
            clearable
          >
            <template #prepend>System Prompt</template>
          </el-input>
          <el-tag v-if="sessionId" type="info" effect="plain" class="mono-num">
            SID: {{ sessionId.slice(0, 10) }}
          </el-tag>
        </div>

        <div v-if="personas.length > 0" class="persona-bar">
          <button
            type="button"
            class="persona-chip"
            :class="{ 'is-active': selectedPersonaId === undefined }"
            @click="selectPersona(undefined)"
          >
            默认直连
          </button>
          <button
            v-for="p in personas.slice(0, 5)"
            :key="p.id"
            type="button"
            class="persona-chip"
            :class="{ 'is-active': selectedPersonaId === p.id }"
            @click="selectPersona(p.id)"
          >
            <span>{{ p.avatar_emoji }}</span>
            <span>{{ p.name }}</span>
          </button>
          <button
            v-if="personas.length > 5"
            type="button"
            class="persona-chip is-more"
            @click="plazaDrawerVisible = true"
          >
            更多 ({{ personas.length }})
          </button>
        </div>

        <div ref="listRef" class="message-list" @click="handleMessageAreaClick">
          <div
            v-for="(msg, idx) in messages"
            :key="msg.id"
            class="message-row"
            :class="msg.role === 'user' ? 'is-user' : 'is-assistant'"
          >
            <div class="bubble">
              <div class="bubble-role-row">
                <span class="bubble-role">
                  {{ msg.role === 'user' ? '我' : msg.modelLabel || 'AILOVE Assistant' }}
                </span>
                <span v-if="msg.role === 'assistant' && msg.loveProfileInjected" class="profile-injected-tag">
                  💞 已结合情感档案
                </span>
              </div>
              <details v-if="msg.reasoning" class="reasoning-box" open>
                <summary>深度思考过程 (Reasoning)</summary>
                <div class="reasoning-text">{{ msg.reasoning }}</div>
              </details>

              <div v-if="msg.role === 'user'" class="bubble-plain">{{ msg.content }}</div>
              <div
                v-else-if="msg.isError || !msg.content"
                class="bubble-plain"
                :class="{ 'is-error': msg.isError }"
              >
                {{ msg.content || (msg.reasoning ? '正在整理最终回答...' : '正在思考...') }}
              </div>
              <div
                v-else
                class="markdown-body"
                v-html="renderMarkdown(msg.content)"
              />

              <!-- 情绪关怀护栏暖心提示卡 -->
              <div
                v-if="msg.role === 'assistant' && msg.emotionCare"
                class="emotion-care-card"
                :class="msg.emotionCare.level === 'crisis' ? 'is-crisis' : 'is-distress'"
              >
                <div class="emotion-care-title">
                  {{ msg.emotionCare.level === 'crisis' ? '🤍' : '🌙' }} {{ msg.emotionCare.title }}
                </div>
                <p class="emotion-care-desc">{{ msg.emotionCare.message }}</p>
                <div v-if="msg.emotionCare.hotlines?.length" class="emotion-hotlines">
                  <button
                    v-for="h in msg.emotionCare.hotlines"
                    :key="h.name"
                    type="button"
                    class="hotline-pill"
                    @click="copyText(h.phone)"
                  >
                    <span>{{ h.name }}</span>
                    <strong class="mono-num">{{ h.phone }}</strong>
                  </button>
                </div>
              </div>

              <div v-if="msg.role === 'assistant' && msg.content" class="bubble-actions">
                <span v-if="msg.tokenUsage" class="bubble-token mono-num">
                  Tokens · {{ msg.tokenUsage }}
                </span>
                <div class="bubble-btns">
                  <button type="button" class="mini-action-btn" @click="handleFavoriteBubble(msg)">
                    ⭐ 收藏
                  </button>
                  <button type="button" class="mini-action-btn" @click="copyText(msg.content)">
                    复制全文
                  </button>
                  <button
                    v-if="idx === lastAssistantIdx && idx > 0 && !sending"
                    type="button"
                    class="mini-action-btn"
                    @click="handleRegenerate"
                  >
                    重新生成
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="starter-bar">
          <button
            type="button"
            class="reply-helper-trigger"
            :disabled="sending"
            @click="replyHelperVisible = true"
          >
            💬 帮我回消息 / 识图拆解
          </button>
          <button
            type="button"
            class="reply-helper-trigger"
            :disabled="sending"
            @click="softenVisible = true"
          >
            🧊 先别发 · 话术柔化
          </button>
          <template v-if="activePersona?.starter_prompts?.length">
            <span class="starter-label">{{ activePersona.avatar_emoji }} 快捷提问：</span>
            <button
              v-for="sp in activePersona.starter_prompts"
              :key="sp"
              type="button"
              class="starter-chip"
              :disabled="sending"
              @click="quickAskStarter(sp)"
            >
              {{ sp }}
            </button>
          </template>
        </div>

        <div class="composer">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="2"
            resize="none"
            placeholder="输入消息，按 Ctrl/Cmd + Enter 快速发送"
            @keydown.ctrl.enter.prevent="handleSend"
            @keydown.meta.enter.prevent="handleSend"
          />
          <el-button v-if="sending && useStream" class="send-btn" @click="handleStop">
            停止生成
          </el-button>
          <el-button v-else type="primary" :loading="sending" class="send-btn" @click="handleSend">
            发送
          </el-button>
        </div>
      </div>
    </div>

    <el-drawer v-model="plazaDrawerVisible" title="AI 智能体广场" size="420px">
      <div class="plaza-cats">
        <button
          v-for="cat in [
            { k: 'all', l: '全部' },
            { k: 'chat_coach', l: '话术' },
            { k: 'dating', l: '约会' },
            { k: 'relationship', l: '关系' },
            { k: 'conflict', l: '修复' },
            { k: 'healing', l: '疗愈' },
          ]"
          :key="cat.k"
          type="button"
          class="persona-chip"
          :class="{ 'is-active': plazaCategory === cat.k }"
          @click="plazaCategory = cat.k"
        >
          {{ cat.l }}
        </button>
      </div>

      <div class="plaza-list">
        <div
          class="plaza-card"
          :class="{ 'is-active': selectedPersonaId === undefined }"
          @click="selectPersona(undefined)"
        >
          <div class="plaza-card-top">
            <span class="plaza-emoji">✨</span>
            <div>
              <div class="plaza-name">默认直连对话</div>
              <div class="plaza-desc">不使用特定角色，直接采用所选大模型配置与系统提示词</div>
            </div>
          </div>
        </div>

        <div
          v-for="p in plazaFilteredPersonas"
          :key="p.id"
          class="plaza-card"
          :class="{ 'is-active': selectedPersonaId === p.id }"
          @click="selectPersona(p.id)"
        >
          <div class="plaza-card-top">
            <span class="plaza-emoji">{{ p.avatar_emoji }}</span>
            <div style="flex: 1; min-width: 0">
              <div class="plaza-name-row">
                <span class="plaza-name">{{ p.name }}</span>
                <span class="plaza-usage mono-num">{{ p.usage_count }} 次</span>
              </div>
              <div class="plaza-desc">{{ p.description }}</div>
            </div>
          </div>
        </div>
      </div>
    </el-drawer>

    <!-- 我的情感档案记忆卡抽屉 -->
    <el-drawer v-model="loveProfileDrawerVisible" title="💞 我的情感背景记忆卡" size="460px">
      <div class="love-drawer-body">
        <div class="love-switch-banner">
          <div>
            <div class="love-switch-title">自动注入 AI 对话上下文</div>
            <div class="love-switch-desc">
              开启后，5 大情感智能体将自动结合你的真实处境，无需每次重复交代前情
            </div>
          </div>
          <el-switch v-model="loveForm.auto_inject" />
        </div>

        <el-form label-position="top" class="love-form">
          <el-form-item label="当前所处的情感阶段">
            <div class="chip-grid">
              <button
                v-for="st in lovePresets.stages"
                :key="st.code"
                type="button"
                class="persona-chip"
                :class="{ 'is-active': loveForm.relationship_stage === st.code }"
                @click="
                  loveForm.relationship_stage =
                    loveForm.relationship_stage === st.code ? '' : st.code
                "
              >
                <span>{{ st.emoji }}</span>
                <span>{{ st.label }}</span>
              </button>
            </div>
          </el-form-item>

          <el-form-item label="对方称呼（可选，用于个性化称呼）">
            <el-input
              v-model="loveForm.partner_nickname"
              maxlength="32"
              placeholder="例如：TA、小林、学姐、男朋友"
              clearable
            />
          </el-form-item>

          <el-form-item label="对方性格 / 依恋特点（可多选，最多 8 个）">
            <div class="chip-grid">
              <button
                v-for="tag in lovePresets.partner_trait_presets"
                :key="tag"
                type="button"
                class="persona-chip"
                :class="{ 'is-active': loveForm.partner_traits.includes(tag) }"
                @click="toggleTraitTag(loveForm.partner_traits, tag)"
              >
                {{ tag }}
              </button>
            </div>
            <div v-if="loveForm.partner_traits.length" class="selected-tags-row">
              <el-tag
                v-for="t in loveForm.partner_traits"
                :key="t"
                size="small"
                closable
                effect="plain"
                @close="toggleTraitTag(loveForm.partner_traits, t)"
              >
                {{ t }}
              </el-tag>
            </div>
            <div class="custom-tag-row">
              <el-input
                v-model="customPartnerTrait"
                size="small"
                maxlength="24"
                placeholder="补充自定义标签，回车添加"
                @keydown.enter.prevent="addCustomPartnerTrait"
              />
              <el-button size="small" plain @click="addCustomPartnerTrait">添加</el-button>
            </div>
          </el-form-item>

          <el-form-item label="我自己的沟通特点（帮助 AI 避免制造内耗）">
            <div class="chip-grid">
              <button
                v-for="tag in lovePresets.my_trait_presets"
                :key="tag"
                type="button"
                class="persona-chip"
                :class="{ 'is-active': loveForm.my_traits.includes(tag) }"
                @click="toggleTraitTag(loveForm.my_traits, tag)"
              >
                {{ tag }}
              </button>
            </div>
          </el-form-item>

          <el-form-item label="当前最核心的情感诉求 / 目标">
            <el-input
              v-model="loveForm.relationship_goal"
              maxlength="160"
              placeholder="例如：自然推进确认关系 / 化解冷战僵局 / 找回恋爱新鲜感"
              clearable
            />
          </el-form-item>

          <el-form-item label="沟通雷区与注意事项">
            <el-input
              v-model="loveForm.communication_taboos"
              maxlength="300"
              placeholder="例如：对方反感连环追问和说教；异地时差 2 小时"
              clearable
            />
          </el-form-item>

          <el-form-item label="补充背景摘要">
            <el-input
              v-model="loveForm.background_notes"
              type="textarea"
              :rows="3"
              maxlength="1200"
              show-word-limit
              placeholder="简述你们认识多久、最近卡在哪件事上，仅保存在你个人账号下严格隔离"
            />
          </el-form-item>
        </el-form>

        <div class="love-drawer-footer">
          <el-button type="danger" plain @click="handleClearLoveProfile">清空档案</el-button>
          <el-button type="primary" :loading="loveProfileSaving" @click="handleSaveLoveProfile">
            保存并生效
          </el-button>
        </div>
      </div>
    </el-drawer>

    <!-- 「帮我回消息 2.0 / 聊天截图识图拆解」快捷弹窗 -->
    <el-dialog
      v-model="replyHelperVisible"
      title="💬 帮我回消息 2.0 · 识图拆解与高情商备选"
      width="600px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="微信聊天截图（可选，最多 3 张，自动识别双方发言与潜台词）">
          <div class="upload-shot-row">
            <div v-for="(imgUrl, i) in replyImages" :key="i" class="shot-thumb-box">
              <img :src="imgUrl" class="shot-thumb-img" alt="聊天截图预览" />
              <button type="button" class="shot-del-btn" @click="removeReplyImage(i)">×</button>
            </div>
            <button
              v-if="replyImages.length < 3"
              type="button"
              class="shot-add-btn"
              @click="replyFileInputRef?.click()"
            >
              <span>＋ 上传截图</span>
              <small>{{ replyImages.length }}/3</small>
            </button>
            <input
              ref="replyFileInputRef"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              style="display: none"
              @change="handleReplyImageChange"
            />
          </div>
          <div class="vision-status-hint">
            {{
              replyPresets.has_vision_model
                ? `👁️ 已就绪识图引擎：${replyPresets.vision_model_label}`
                : '💡 上传截图需先在「AI 模型配置」启用 deepseek-flash 或通义千问 VL（未填 Key 时为演示模式）'
            }}
          </div>
        </el-form-item>

        <el-form-item label="粘贴对方发来的原话 / 补充说明（上传截图时可选）">
          <el-input
            v-model="replyForm.partner_message"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="例如：最近项目真的太忙了，改天有空再约你吧"
          />
        </el-form-item>

        <el-form-item label="当前互动场景">
          <div class="chip-grid">
            <button
              v-for="sc in replyPresets.scenes"
              :key="sc.code"
              type="button"
              class="persona-chip"
              :class="{ 'is-active': replyForm.scene === sc.code }"
              :title="sc.desc"
              @click="replyForm.scene = sc.code"
            >
              {{ sc.label }}
            </button>
          </div>
        </el-form-item>

        <el-form-item label="期望回复语气">
          <div class="tone-grid">
            <button
              v-for="tn in replyPresets.tones"
              :key="tn.code"
              type="button"
              class="tone-card"
              :class="{ 'is-active': replyForm.tone === tn.code }"
              @click="replyForm.tone = tn.code"
            >
              <span class="tone-name">{{ tn.label }}</span>
              <span class="tone-desc">{{ tn.desc }}</span>
            </button>
          </div>
        </el-form-item>

        <el-form-item label="我真实想表达的核心意思（可选）">
          <el-input
            v-model="replyForm.my_intent"
            maxlength="400"
            placeholder="例如：想体面收尾不显得粘人，同时留个轻松小钩子"
            clearable
          />
        </el-form-item>

        <el-form-item label="前文背景补充（可选）">
          <el-input
            v-model="replyForm.context"
            maxlength="800"
            placeholder="例如：之前聊得很热络，这两天回复间隔突然拉长"
            clearable
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="reply-dialog-footer">
          <span class="reply-dialog-hint">
            {{
              loveProfileActive
                ? '💞 将自动结合你的情感档案记忆卡生成建议'
                : '💡 搭配「情感档案」记忆卡效果更贴合'
            }}
          </span>
          <div>
            <el-button @click="replyHelperVisible = false">取消</el-button>
            <el-button type="primary" :loading="sending" @click="handleSubmitReplyHelper">
              立即拆解并生成 3 条回复
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 「先别发！」情绪降温与话术柔化弹窗 -->
    <el-dialog
      v-model="softenVisible"
      title="🧊 先别发！情绪降温与话术柔化器"
      width="560px"
      destroy-on-close
    >
      <el-form label-position="top">
        <el-form-item label="把气头上/委屈时打好的草稿贴进来" required>
          <el-input
            v-model="softenForm.draft_message"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="例如：算了随便你吧，反正你从来也不在乎我的感受"
          />
        </el-form-item>

        <el-form-item label="此刻你的情绪温度">
          <div class="tone-grid">
            <button
              v-for="lv in softenIntensities"
              :key="lv.code"
              type="button"
              class="tone-card"
              :class="{ 'is-active': softenForm.intensity === lv.code }"
              @click="softenForm.intensity = lv.code"
            >
              <span class="tone-name">{{ lv.label }}</span>
              <span class="tone-desc">{{ lv.desc }}</span>
            </button>
          </div>
        </el-form-item>

        <el-form-item label="前情原因（可选）">
          <el-input
            v-model="softenForm.context"
            maxlength="800"
            placeholder="例如：约定好一起吃晚饭，对方临时放鸽子还没道歉"
            clearable
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="reply-dialog-footer">
          <span class="reply-dialog-hint">🌿 帮你既不委屈自己、又不把关系推向对抗</span>
          <div>
            <el-button @click="softenVisible = false">取消</el-button>
            <el-button type="primary" :loading="sending" @click="handleSubmitSoftenDraft">
              降温改写为 3 个版本
            </el-button>
          </div>
        </div>
      </template>
    </el-dialog>

    <!-- 高情商话术收藏夹抽屉 -->
    <el-drawer v-model="favoritesDrawerVisible" title="⭐ 高情商话术收藏夹" size="440px">
      <div class="plaza-cats" style="margin-bottom: 12px">
        <button
          v-for="cat in [
            { k: 'all', l: '全部' },
            { k: 'reply_helper', l: '回消息' },
            { k: 'soften', l: '先别发' },
            { k: 'chat', l: '对话' },
            { k: 'custom', l: '自定义' },
          ]"
          :key="cat.k"
          type="button"
          class="persona-chip"
          :class="{ 'is-active': favoriteFilter === cat.k }"
          @click="favoriteFilter = cat.k; void loadFavorites()"
        >
          {{ cat.l }}
        </button>
      </div>

      <div class="fav-add-box">
        <el-input
          v-model="newFavContent"
          type="textarea"
          :rows="2"
          placeholder="手动存入一句高情商话术/破冰金句..."
          maxlength="1200"
        />
        <div class="fav-add-row">
          <el-input v-model="newFavNote" size="small" placeholder="适用备注（可选）" clearable />
          <el-button size="small" type="primary" plain @click="handleAddManualFavorite">保存</el-button>
        </div>
      </div>

      <div v-loading="favoritesLoading" class="fav-list">
        <el-empty v-if="favoriteItems.length === 0" description="暂无收藏话术，可在对话或工具结果中点击「⭐ 收藏」" />
        <div v-for="fav in favoriteItems" :key="fav.id" class="fav-card">
          <div class="fav-head">
            <el-tag size="small" effect="plain">{{ fav.scene_label || fav.category }}</el-tag>
            <div>
              <el-button link size="small" type="primary" @click="copyText(fav.content)">复制</el-button>
              <el-button link size="small" type="danger" @click="handleDeleteFavorite(fav.id)">删除</el-button>
            </div>
          </div>
          <div class="fav-content">{{ fav.content }}</div>
          <div v-if="fav.note" class="fav-note">备注：{{ fav.note }}</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.model-opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.workbench-shell {
  display: flex;
  gap: 16px;
  height: calc(100vh - 196px);
  min-height: 500px;
}

.history-pane {
  width: 248px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 14px;
  overflow: hidden;
}

.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
  margin-bottom: 10px;
}

.history-empty {
  font-size: 12.5px;
  color: var(--ailove-ink-muted);
  line-height: 1.6;
  padding: 20px 6px;
  text-align: center;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.history-item {
  padding: 10px 11px;
  border-radius: 10px;
  border: 1px solid transparent;
  background: var(--ailove-subtle);
  cursor: pointer;
  transition: all 0.15s var(--ailove-ease);
}

.history-item:hover {
  border-color: var(--ailove-brand-200);
}

.history-item.is-active {
  background: var(--ailove-brand-50);
  border-color: var(--ailove-brand-200);
}

.history-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--ailove-ink-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-meta {
  margin-top: 5px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.history-model {
  font-size: 11px;
  color: var(--ailove-ink-muted);
}

.history-ops {
  opacity: 0;
  transition: opacity 0.14s;
}

.history-item:hover .history-ops,
.history-item.is-active .history-ops {
  opacity: 1;
}

.playground-card {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.prompt-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  background: var(--ailove-subtle);
  border-radius: 14px;
  border: 1px solid var(--ailove-border);
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.message-row {
  display: flex;
}

.message-row.is-user {
  justify-content: flex-end;
}

.bubble {
  max-width: 82%;
  padding: 13px 16px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid var(--ailove-border);
  box-shadow: 0 2px 8px rgba(26, 22, 29, 0.04);
}

.message-row.is-user .bubble {
  background: linear-gradient(135deg, #d84361 0%, #c83553 100%);
  color: #ffffff;
  border-color: transparent;
  box-shadow: var(--ailove-shadow-brand);
}

.bubble-role {
  font-size: 11px;
  font-weight: 600;
  opacity: 0.72;
  margin-bottom: 6px;
}

.reasoning-box {
  margin: 6px 0 10px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--ailove-subtle);
  border-left: 3px solid var(--ailove-brand-200);
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
}

.reasoning-box summary {
  cursor: pointer;
  font-weight: 600;
  color: var(--ailove-ink-muted);
  margin-bottom: 4px;
}

.reasoning-text {
  white-space: pre-wrap;
  line-height: 1.6;
}

.bubble-plain {
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble-plain.is-error {
  color: var(--el-color-danger);
}

.bubble-actions {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px dashed var(--ailove-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.bubble-token {
  font-size: 11px;
  color: var(--ailove-ink-muted);
}

.bubble-btns {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.mini-action-btn {
  border: none;
  background: transparent;
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
  cursor: pointer;
  transition: all 0.14s;
}

.mini-action-btn:hover {
  background: var(--ailove-subtle);
  color: var(--ailove-brand-600);
}

/* Markdown 富文本排版样式 */
.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: var(--ailove-ink-primary);
  word-break: break-word;
}

.markdown-body :deep(.md-p) {
  margin: 0 0 8px;
}

.markdown-body :deep(.md-p:last-child) {
  margin-bottom: 0;
}

.markdown-body :deep(.md-h) {
  margin: 12px 0 6px;
  font-family: var(--ailove-font-display);
  font-weight: 700;
  color: var(--ailove-ink-primary);
}

.markdown-body :deep(.md-h1) {
  font-size: 18px;
}
.markdown-body :deep(.md-h2) {
  font-size: 16px;
}
.markdown-body :deep(.md-h3),
.markdown-body :deep(.md-h4) {
  font-size: 14.5px;
}

.markdown-body :deep(.md-list) {
  margin: 6px 0 8px;
  padding-left: 20px;
}

.markdown-body :deep(.md-list li) {
  margin: 3px 0;
}

.markdown-body :deep(.md-quote) {
  margin: 8px 0;
  padding: 6px 12px;
  border-left: 3px solid var(--ailove-brand-400);
  background: var(--ailove-subtle);
  border-radius: 0 8px 8px 0;
  color: var(--ailove-ink-secondary);
}

.markdown-body :deep(.md-hr) {
  border: none;
  border-top: 1px solid var(--ailove-border);
  margin: 12px 0;
}

.markdown-body :deep(.md-inline-code) {
  font-family: var(--ailove-font-mono);
  font-size: 12.5px;
  background: rgba(200, 53, 83, 0.08);
  color: #b52c49;
  padding: 1px 6px;
  border-radius: 5px;
}

.markdown-body :deep(.md-code-block) {
  margin: 8px 0;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid rgba(26, 22, 29, 0.14);
  background: #1d1922;
}

.markdown-body :deep(.md-code-head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #27222d;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.markdown-body :deep(.md-code-lang) {
  font-family: var(--ailove-font-mono);
  font-size: 11px;
  color: #c7bfd0;
  text-transform: lowercase;
}

.markdown-body :deep(.md-copy-btn) {
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: transparent;
  color: #e6e0ec;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}

.markdown-body :deep(.md-copy-btn:hover) {
  background: rgba(255, 255, 255, 0.1);
}

.markdown-body :deep(.md-pre) {
  margin: 0;
  padding: 12px 14px;
  overflow-x: auto;
  font-family: var(--ailove-font-mono);
  font-size: 12.5px;
  line-height: 1.55;
  color: #f3eff7;
}

.markdown-body :deep(.md-table-wrap) {
  overflow-x: auto;
  margin: 8px 0;
}

.markdown-body :deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.markdown-body :deep(.md-table th),
.markdown-body :deep(.md-table td) {
  border: 1px solid var(--ailove-border);
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(.md-table th) {
  background: var(--ailove-subtle);
  font-weight: 600;
}

.markdown-body :deep(.md-link) {
  color: var(--ailove-brand-600);
  text-decoration: underline;
}

.composer {
  margin-top: 14px;
  display: flex;
  gap: 12px;
  align-items: stretch;
}

.send-btn {
  width: 96px;
  height: auto;
  border-radius: 10px;
}

@media (max-width: 900px) {
  .history-pane {
    display: none;
  }
}

.persona-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0 6px;
}

.persona-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--ailove-border);
  background: var(--ailove-subtle);
  color: var(--ailove-ink-secondary);
  font-size: 12.5px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.16s;
}

.persona-chip:hover {
  border-color: var(--ailove-brand-200);
  color: var(--ailove-brand-600);
}

.persona-chip.is-active {
  background: var(--ailove-brand-50);
  border-color: var(--ailove-brand-500);
  color: var(--ailove-brand-600);
}

.starter-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.starter-label {
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.starter-chip {
  border: 1px dashed var(--ailove-brand-200);
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  cursor: pointer;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.starter-chip:hover:not(:disabled) {
  background: var(--ailove-brand-600);
  color: #ffffff;
}

.plaza-cats {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.plaza-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.plaza-card {
  border: 1px solid var(--ailove-border);
  background: var(--ailove-surface);
  border-radius: 12px;
  padding: 12px 14px;
  cursor: pointer;
  transition: all 0.18s;
}

.plaza-card:hover,
.plaza-card.is-active {
  border-color: var(--ailove-brand-500);
  background: var(--ailove-brand-50);
}

.plaza-card-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.plaza-emoji {
  font-size: 22px;
  line-height: 1.2;
}

.plaza-name-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.plaza-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.plaza-usage {
  font-size: 11.5px;
  color: var(--ailove-ink-muted);
}

.plaza-desc {
  margin-top: 4px;
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
  line-height: 1.5;
}

.history-item.is-pinned {
  border-left: 3px solid var(--ailove-brand-500);
}

.history-title-row {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.pin-mark {
  font-size: 12px;
  flex-shrink: 0;
}

.history-persona-badge {
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(200, 53, 83, 0.08);
  color: var(--ailove-brand-600);
  font-size: 11px;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bubble-role-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
}

.bubble-role-row .bubble-role {
  margin-bottom: 0;
}

.profile-injected-tag {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
  border: 1px solid var(--ailove-brand-200);
  white-space: nowrap;
}

.emotion-care-card {
  margin-top: 10px;
  padding: 11px 13px;
  border-radius: 12px;
  border: 1px solid #f2c6cf;
  background: linear-gradient(135deg, #fff6f7 0%, #fffaf4 100%);
}

.emotion-care-card.is-crisis {
  border-color: #d84361;
  background: linear-gradient(135deg, #fff1f3 0%, #fff7ed 100%);
  box-shadow: 0 3px 12px rgba(200, 53, 83, 0.12);
}

.emotion-care-title {
  font-size: 13px;
  font-weight: 700;
  color: #9f1f3a;
  margin-bottom: 4px;
}

.emotion-care-desc {
  margin: 0 0 8px;
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ailove-ink-secondary);
}

.emotion-hotlines {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.hotline-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #efc2cb;
  background: #ffffff;
  color: #9f1f3a;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.hotline-pill:hover {
  background: #fff1f3;
  border-color: #c83553;
}

.reply-helper-trigger {
  border: 1px solid var(--ailove-brand-400);
  background: linear-gradient(135deg, #fff2f5 0%, #ffe8ee 100%);
  color: var(--ailove-brand-600);
  font-size: 12px;
  font-weight: 600;
  padding: 4px 11px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
}

.reply-helper-trigger:hover:not(:disabled) {
  background: var(--ailove-brand-600);
  color: #ffffff;
}

.love-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.love-switch-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--ailove-brand-50);
  border: 1px solid var(--ailove-brand-200);
}

.love-switch-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.love-switch-desc {
  margin-top: 2px;
  font-size: 12px;
  color: var(--ailove-ink-secondary);
  line-height: 1.5;
}

.chip-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.selected-tags-row {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.custom-tag-row {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.love-drawer-footer {
  display: flex;
  justify-content: space-between;
  padding-top: 10px;
  border-top: 1px solid var(--ailove-border);
}

.tone-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.tone-card {
  text-align: left;
  padding: 9px 11px;
  border-radius: 10px;
  border: 1px solid var(--ailove-border);
  background: var(--ailove-subtle);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 2px;
  transition: all 0.15s;
}

.tone-card:hover,
.tone-card.is-active {
  border-color: var(--ailove-brand-500);
  background: var(--ailove-brand-50);
}

.tone-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--ailove-ink-primary);
}

.tone-desc {
  font-size: 11.5px;
  color: var(--ailove-ink-secondary);
  line-height: 1.4;
}

.reply-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.reply-dialog-hint {
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.history-foot-ops {
  display: flex;
  gap: 8px;
  padding-top: 10px;
  margin-top: 8px;
  border-top: 1px solid var(--ailove-border);
}

.incognito-banner {
  padding: 8px 12px;
  border-radius: 10px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 12.5px;
  margin-bottom: 10px;
}

.upload-shot-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.shot-thumb-box {
  position: relative;
  width: 78px;
  height: 78px;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--ailove-border);
}

.shot-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.shot-del-btn {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  cursor: pointer;
  line-height: 1;
}

.shot-add-btn {
  width: 78px;
  height: 78px;
  border-radius: 10px;
  border: 1px dashed var(--ailove-brand-400);
  background: var(--ailove-brand-50);
  color: var(--ailove-brand-600);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-size: 12px;
}

.vision-status-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ailove-ink-muted);
}

.fav-add-box {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
  padding: 10px;
  border-radius: 10px;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border);
}

.fav-add-row {
  display: flex;
  gap: 8px;
}

.fav-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.fav-card {
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--ailove-border);
  background: #fff;
}

.fav-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.fav-content {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ailove-ink-primary);
  white-space: pre-wrap;
}

.fav-note {
  margin-top: 6px;
  font-size: 12px;
  color: var(--ailove-ink-muted);
}
</style>
