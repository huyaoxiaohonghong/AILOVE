<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from '@/plugins/element-plus'
import {
  ChatDotRound,
  Check,
  Close,
  MagicStick,
  Plus,
  Refresh,
  Right,
} from '@element-plus/icons-vue'
import {
  createFavoriteReply,
  streamAiChat,
  type EmotionCareNotice,
  type InvokedSkillMeta,
} from '@/api/ai'
import { fetchCallableSkills, type KBSkillItem } from '@/api/kb'
import { applyMascotProfilePatch } from '@/api/mascot'
import MascotLianFigure from '@/components/MascotLianFigure.vue'
import { LIAN_SYSTEM_PROMPT, useMascotStore } from '@/stores/mascot'
import {
  clamp,
  classifyHitZone,
  computeGazeOffset,
  StreamingChoreographyParser,
  type HitZone,
  type MascotToolDirective,
} from '@/utils/mascotBrain'

interface CabinMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  favorited?: boolean
  invokedSkills?: InvokedSkillMeta[]
  toolCard?: MascotToolDirective | null
  toolApplied?: boolean
  actionHint?: {
    label: string
    path: string
  } | null
}

interface BurstParticle {
  id: number
  symbol: string
  dx: number
  dy: number
  scale: number
}

interface TextSegment {
  text: string
  bold: boolean
}

const AVATAR_W = 104
const AVATAR_H = 116
const EDGE_MARGIN = 18

const QUICK_PROMPTS = [
  'Ta 已读不回怎么高情商破冰？',
  '好生气想发狠话，先别发帮我降温',
  '聊天截图怎么直接识图分析？',
  '心情有点焦虑，陪我做个放松呼吸',
]

const MOOD_CHOICES = [
  { score: 1, emoji: '🌧️', label: '低落' },
  { score: 2, emoji: '🥺', label: '委屈' },
  { score: 3, emoji: '☁️', label: '平静' },
  { score: 4, emoji: '🌷', label: '不错' },
  { score: 5, emoji: '✨', label: '心动' },
]

const route = useRoute()
const router = useRouter()
const mascotStore = useMascotStore()

const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const viewportHeight = ref(typeof window !== 'undefined' ? window.innerHeight : 800)

// Real-time gaze tracking & drag pendulum physics
const gazeX = ref(0)
const gazeY = ref(0)
const dragTiltDeg = ref(0)
const isDragging = ref(false)
const hasMoved = ref(false)
const dragX = ref(0)
const dragY = ref(0)
const pointerStartX = ref(0)
const pointerStartY = ref(0)
const avatarStartX = ref(0)
const avatarStartY = ref(0)
let prevDragClientX = 0
let activeHitZone: HitZone = 'body'
let rubAccumX = 0
let rubTriggered = false
let longPressTimer: number | null = null
let longPressFired = false
let recentTapTimes: number[] = []
let lastGazeTs = 0
let autonomousTimer: number | null = null

// Playful feedback particles
const bouncing = ref(false)
const burstParticles = ref<BurstParticle[]>([])
let bounceTimer: number | null = null
let particleSeq = 1

// QA Cabin & interactive widgets
const inputText = ref('')
const sending = ref(false)
const messages = ref<CabinMessage[]>([])
const emotionCare = ref<EmotionCareNotice | null>(null)
const chatScrollRef = ref<HTMLElement | null>(null)
const callableSkills = ref<KBSkillItem[]>([])
const selectedSkillId = ref<number | null>(null)
const showMemories = ref(false)
const checkingIn = ref(false)
let abortController: AbortController | null = null

// Built-in 4-4-4 Calm Breathing Ritual
const breathingActive = ref(false)
const breathingRemainSec = ref(30)
const breathingPhase = ref<'吸气 (4s)' | '屏息 (4s)' | '慢呼气 (4s)'>('吸气 (4s)')
const breathingScale = ref(1)
let breathingTimer: number | null = null

const clampedTop = computed(() => {
  const maxTop = Math.max(72, viewportHeight.value - AVATAR_H - 18)
  const desired = mascotStore.yRatio * viewportHeight.value - AVATAR_H / 2
  return Math.min(maxTop, Math.max(72, desired))
})

const avatarCenter = computed(() => {
  const left = isDragging.value
    ? dragX.value
    : mascotStore.dockSide === 'left'
      ? EDGE_MARGIN
      : Math.max(EDGE_MARGIN, viewportWidth.value - AVATAR_W - EDGE_MARGIN)
  const top = isDragging.value ? dragY.value : clampedTop.value
  return { x: left + AVATAR_W / 2, y: top + AVATAR_H * 0.42 }
})

const avatarStyle = computed(() => {
  if (isDragging.value) {
    return {
      left: `${dragX.value}px`,
      top: `${dragY.value}px`,
      right: 'auto',
      transition: 'none',
    }
  }
  const topPx = `${Math.round(clampedTop.value)}px`
  if (mascotStore.dockSide === 'left') {
    return {
      left: `${EDGE_MARGIN}px`,
      top: topPx,
      right: 'auto',
      transition: 'left 0.36s cubic-bezier(0.22, 1, 0.36, 1), top 0.36s cubic-bezier(0.22, 1, 0.36, 1)',
    }
  }
  const rightX = Math.max(EDGE_MARGIN, viewportWidth.value - AVATAR_W - EDGE_MARGIN)
  return {
    left: `${rightX}px`,
    top: topPx,
    right: 'auto',
    transition: 'left 0.36s cubic-bezier(0.22, 1, 0.36, 1), top 0.36s cubic-bezier(0.22, 1, 0.36, 1)',
  }
})

const minimizedStyle = computed(() => {
  const topPx = `${Math.round(clampedTop.value + 16)}px`
  return mascotStore.dockSide === 'left'
    ? { left: '0px', right: 'auto', top: topPx }
    : { right: '0px', left: 'auto', top: topPx }
})

const cabinPositionStyle = computed(() => {
  const cabinW = Math.min(390, viewportWidth.value - 28)
  const cabinH = Math.min(560, viewportHeight.value - 84)
  const avatarX =
    mascotStore.dockSide === 'left'
      ? EDGE_MARGIN
      : Math.max(EDGE_MARGIN, viewportWidth.value - AVATAR_W - EDGE_MARGIN)

  let left = mascotStore.dockSide === 'right' ? avatarX - cabinW - 14 : avatarX + AVATAR_W + 14
  if (left < 14 || left + cabinW > viewportWidth.value - 14) {
    left = Math.max(14, viewportWidth.value - cabinW - 14)
  }
  const desiredTop = clampedTop.value + AVATAR_H - cabinH + 16
  const top = Math.min(Math.max(16, viewportHeight.value - cabinH - 18), Math.max(66, desiredTop))

  return {
    width: `${cabinW}px`,
    maxHeight: `${cabinH}px`,
    left: `${Math.round(left)}px`,
    top: `${Math.round(top)}px`,
  }
})

const affinityProgress = computed(() => {
  const cur = mascotStore.pad.affinity
  const next = mascotStore.nextLevelAffinity
  if (!next) return 100
  return Math.round(clamp((cur / next) * 100, 5, 100))
})

async function loadCallableSkills() {
  try {
    const res = await fetchCallableSkills()
    callableSkills.value = res.items
  } catch {
    // ignore
  }
}

function updateViewport() {
  viewportWidth.value = window.innerWidth
  viewportHeight.value = window.innerHeight
}

function handleGlobalPointerMove(e: PointerEvent) {
  const now = performance.now()
  if (now - lastGazeTs < 33) return
  lastGazeTs = now
  const { gx, gy } = computeGazeOffset(e.clientX, e.clientY, avatarCenter.value.x, avatarCenter.value.y)
  gazeX.value = gx
  gazeY.value = gy
}

function emitParticles(symbol = '♥', count = 5) {
  bouncing.value = false
  window.requestAnimationFrame(() => {
    bouncing.value = true
  })
  if (bounceTimer !== null) window.clearTimeout(bounceTimer)
  bounceTimer = window.setTimeout(() => {
    bouncing.value = false
    bounceTimer = null
  }, 520)

  const batch: BurstParticle[] = Array.from({ length: count }, (_, idx) => ({
    id: particleSeq++,
    symbol,
    dx: (idx - (count - 1) / 2) * 15 + (Math.random() * 8 - 4),
    dy: -40 - Math.random() * 28,
    scale: 0.78 + Math.random() * 0.45,
  }))
  burstParticles.value = [...burstParticles.value, ...batch]
  window.setTimeout(() => {
    const removeIds = new Set(batch.map((item) => item.id))
    burstParticles.value = burstParticles.value.filter((item) => !removeIds.has(item.id))
  }, 950)
}

function clearLongPress() {
  if (longPressTimer !== null) {
    window.clearTimeout(longPressTimer)
    longPressTimer = null
  }
}

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  const target = e.currentTarget as HTMLElement
  target.setPointerCapture(e.pointerId)

  const rect = target.getBoundingClientRect()
  const relX = (e.clientX - rect.left) / Math.max(1, rect.width)
  const relY = (e.clientY - rect.top) / Math.max(1, rect.height)
  activeHitZone = classifyHitZone(relX, relY)

  isDragging.value = true
  hasMoved.value = false
  rubAccumX = 0
  rubTriggered = false
  longPressFired = false
  pointerStartX.value = e.clientX
  pointerStartY.value = e.clientY
  prevDragClientX = e.clientX

  const currentLeft =
    mascotStore.dockSide === 'left'
      ? EDGE_MARGIN
      : Math.max(EDGE_MARGIN, viewportWidth.value - AVATAR_W - EDGE_MARGIN)
  avatarStartX.value = currentLeft
  avatarStartY.value = clampedTop.value
  dragX.value = currentLeft
  dragY.value = clampedTop.value

  clearLongPress()
  longPressTimer = window.setTimeout(() => {
    if (isDragging.value && !hasMoved.value && !rubTriggered) {
      longPressFired = true
      emitParticles('💗', 6)
      void mascotStore.dispatchGesture('long_hug')
    }
  }, 580)
}

function onPointerMove(e: PointerEvent) {
  if (!isDragging.value) return
  const dx = e.clientX - pointerStartX.value
  const dy = e.clientY - pointerStartY.value
  const stepDx = e.clientX - prevDragClientX
  prevDragClientX = e.clientX

  // 头顶横向来回轻抚 -> 识别为「摸头杀」，不触发位移拖拽
  if (!hasMoved.value && (activeHitZone === 'head' || activeHitZone === 'ear') && Math.abs(dy) < 26) {
    rubAccumX += Math.abs(stepDx)
    if (rubAccumX >= 52 && !rubTriggered) {
      rubTriggered = true
      clearLongPress()
      emitParticles('♥', 6)
      void mascotStore.dispatchGesture('rub_head')
    }
    if (rubAccumX >= 14) return
  }

  if (!hasMoved.value && Math.hypot(dx, dy) > 9) {
    hasMoved.value = true
    clearLongPress()
  }
  if (hasMoved.value) {
    dragX.value = clamp(avatarStartX.value + dx, 8, Math.max(8, viewportWidth.value - AVATAR_W - 8))
    dragY.value = clamp(avatarStartY.value + dy, 66, Math.max(66, viewportHeight.value - AVATAR_H - 12))
    dragTiltDeg.value = clamp(-stepDx * 1.15, -22, 22)
  }
}

function onPointerUp(e: PointerEvent) {
  if (!isDragging.value) return
  clearLongPress()
  try {
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {
    // ignore
  }
  const wasDragged = hasMoved.value
  isDragging.value = false
  hasMoved.value = false
  dragTiltDeg.value = 0

  if (longPressFired || rubTriggered) {
    longPressFired = false
    rubTriggered = false
    return
  }

  if (wasDragged) {
    const centerX = dragX.value + AVATAR_W / 2
    const nextSide = centerX < viewportWidth.value / 2 ? 'left' : 'right'
    const nextYRatio = (dragY.value + AVATAR_H / 2) / Math.max(1, viewportHeight.value)
    mascotStore.setDockPosition(nextSide, nextYRatio)
    emitParticles('✨', 3)
    void mascotStore.dispatchGesture('drag_swing')
    return
  }

  // Combo rapid tap detection (>= 5 taps in 2s -> dizzy!)
  const now = Date.now()
  recentTapTimes = recentTapTimes.filter((t) => now - t < 2000)
  recentTapTimes.push(now)
  if (recentTapTimes.length >= 5) {
    recentTapTimes = []
    emitParticles('⭐', 6)
    void mascotStore.dispatchGesture('combo_dizzy')
    return
  }

  // Hit-zone micro-interactions when cabin is closed
  if (!mascotStore.drawerOpen && activeHitZone === 'ear') {
    emitParticles('!', 3)
    void mascotStore.dispatchGesture('pull_ear')
    return
  }
  if (!mascotStore.drawerOpen && activeHitZone === 'tail') {
    emitParticles('💗', 4)
    void mascotStore.dispatchGesture('pull_tail')
    return
  }
  if (!mascotStore.drawerOpen && activeHitZone === 'cheek') {
    emitParticles('♥', 4)
    void mascotStore.dispatchGesture('poke_cheek')
    return
  }

  // Body tap or open state toggles QA Cabin
  emitParticles('♥', 5)
  mascotStore.toggleDrawer()
}

function onEdgePeekClick() {
  mascotStore.setMinimized(false)
  emitParticles('✨', 4)
  void mascotStore.dispatchGesture('edge_peek')
}

function scrollToBottom() {
  nextTick(() => {
    if (chatScrollRef.value) {
      chatScrollRef.value.scrollTop = chatScrollRef.value.scrollHeight
    }
  })
}

function inferActionHint(prompt: string, reply: string): CabinMessage['actionHint'] {
  const combined = `${prompt}\n${reply}`
  if (/知识库|wiki|skill|整包|上传文档/i.test(combined)) {
    return { label: '去知识库 & Skill 工坊', path: '/knowledge-wiki' }
  }
  if (/智能体|人格|persona/i.test(combined)) {
    return { label: '去智能体工坊看看', path: '/ai-personas' }
  }
  if (/模型|配置|备用链路|api key/i.test(combined)) {
    return { label: '去 AI 模型配置', path: '/ai-config' }
  }
  return null
}

function parseLineSegments(line: string): TextSegment[] {
  const parts = line.split(/(\*\*[^*]+\*\*)/g)
  return parts
    .filter((p) => p.length > 0)
    .map((p) => {
      if (p.startsWith('**') && p.endsWith('**') && p.length > 4) {
        return { text: p.slice(2, -2), bold: true }
      }
      return { text: p, bold: false }
    })
}

function stopBreathing() {
  if (breathingTimer !== null) {
    window.clearInterval(breathingTimer)
    breathingTimer = null
  }
  breathingActive.value = false
  breathingScale.value = 1
}

function startCalmBreathing(seconds = 30) {
  stopBreathing()
  breathingActive.value = true
  breathingRemainSec.value = Math.max(12, Math.min(60, seconds))
  mascotStore.setMood('comfort')
  let elapsed = 0
  const updatePhase = () => {
    const cycle = elapsed % 12
    if (cycle < 4) {
      breathingPhase.value = '吸气 (4s)'
      breathingScale.value = 1.24
    } else if (cycle < 8) {
      breathingPhase.value = '屏息 (4s)'
      breathingScale.value = 1.24
    } else {
      breathingPhase.value = '慢呼气 (4s)'
      breathingScale.value = 0.88
    }
  }
  updatePhase()
  breathingTimer = window.setInterval(() => {
    elapsed += 1
    breathingRemainSec.value -= 1
    if (breathingRemainSec.value <= 0) {
      stopBreathing()
      mascotStore.triggerHappy('做完深呼吸感觉松快一点了吗？恋恋一直都在 💗', 3200)
      return
    }
    updatePhase()
  }, 1000)
}

async function handleExecuteToolCard(msg: CabinMessage) {
  const tool = msg.toolCard
  if (!tool) return

  if (tool.type === 'start_calm_breathing') {
    startCalmBreathing(tool.seconds || 30)
    return
  }

  if (tool.type === 'propose_profile_update' && tool.patch) {
    if (msg.toolApplied) return
    try {
      await applyMascotProfilePatch(tool.patch)
      msg.toolApplied = true
      mascotStore.triggerHappy('帮你记进情感档案啦，以后聊起来更懂你们~', 2600)
      ElMessage.success('已顺手同步到你的情感档案')
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : '同步情感档案失败')
    }
    return
  }

  if (tool.type === 'open_reply_helper' || tool.type === 'open_soften_draft') {
    mascotStore.setPendingToolIntent(tool)
    mascotStore.closeDrawer()
    await router.push('/ai-playground')
    ElMessage.success('已为你自动带入文本到 AI 调试台')
  }
}

async function handleMoodCheckin(score: number) {
  if (checkingIn.value) return
  checkingIn.value = true
  try {
    const res = await mascotStore.recordMoodCheckin(score)
    messages.value.push({
      id: `ci_${Date.now()}`,
      role: 'assistant',
      content: `【今日心情：${res.label}】\n${res.reply}`,
      toolCard:
        score <= 2
          ? { type: 'start_calm_breathing', label: '跟恋恋做 30 秒呼吸放松', seconds: 30 }
          : null,
    })
    emitParticles(score >= 4 ? '✨' : '💗', 5)
    scrollToBottom()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '打卡失败，请稍后重试')
  } finally {
    checkingIn.value = false
  }
}

async function handleForgetMemory(id: number) {
  try {
    await mascotStore.forgetMemory(id)
    ElMessage.success('恋恋已经帮你忘掉这条记忆啦')
  } catch {
    ElMessage.error('删除记忆失败')
  }
}

function handleNewTopic() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  stopBreathing()
  sending.value = false
  messages.value = []
  emotionCare.value = null
  mascotStore.resetSession()
  mascotStore.showBubble('新话题准备好啦，想问什么都可以~', 2600)
}

function handleNavigate(path: string, passSession = false) {
  mascotStore.closeDrawer()
  if (passSession && mascotStore.sessionId && path === '/ai-playground') {
    router.push({ path, query: { session_id: mascotStore.sessionId } })
    return
  }
  router.push(path)
}

async function handleFavorite(msg: CabinMessage) {
  if (!msg.content.trim() || msg.favorited) return
  try {
    await createFavoriteReply({
      content: msg.content.trim(),
      category: 'chat',
      scene_label: '恋恋小课堂',
      note: '来自看板娘恋恋的回答',
    })
    msg.favorited = true
    mascotStore.triggerHappy('帮你在灵感库收藏好啦~', 2200)
    ElMessage.success('已加入灵感收藏夹')
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : '收藏失败，请稍后重试')
  }
}

async function sendPrompt(rawText?: string) {
  const text = (rawText ?? inputText.value).trim()
  if (!text || sending.value) return

  if (!rawText) inputText.value = ''

  const userMsg: CabinMessage = {
    id: `u_${Date.now()}`,
    role: 'user',
    content: text,
  }
  const assistantMsg: CabinMessage = {
    id: `a_${Date.now() + 1}`,
    role: 'assistant',
    content: '',
    toolCard: null,
  }

  messages.value.push(userMsg, assistantMsg)
  emotionCare.value = null
  sending.value = true
  mascotStore.setMood('thinking')
  mascotStore.setSpeaking(false)
  scrollToBottom()

  abortController = new AbortController()
  let receivedCare = false
  let receivedEmoTag = false

  const parser = new StreamingChoreographyParser({
    onEmo: (dir) => {
      receivedEmoTag = true
      if (!receivedCare) {
        mascotStore.applyEmoDirective(dir)
      }
    },
    onTool: (tool) => {
      assistantMsg.toolCard = tool
      scrollToBottom()
    },
    onText: (cleanChunk) => {
      if (!receivedCare && !receivedEmoTag && mascotStore.mood === 'thinking') {
        mascotStore.setMood('idle')
      }
      mascotStore.setSpeaking(true)
      assistantMsg.content += cleanChunk
      scrollToBottom()
    },
    onSyllablePulse: (openness) => {
      mascotStore.pulseSyllableMouth(openness)
    },
  })

  try {
    await streamAiChat(
      {
        message: text,
        session_id: mascotStore.sessionId || undefined,
        system_prompt: LIAN_SYSTEM_PROMPT,
        temperature: 0.75,
        use_love_profile: true,
        skill_ids: selectedSkillId.value ? [selectedSkillId.value] : [],
        auto_match_skills: true,
        mascot_mode: true,
        mascot_context: mascotStore.currentContextHint || `当前位于 Web 页面 ${route.path}`,
        ephemeral_history: messages.value
          .slice(0, -2)
          .slice(-6)
          .map((item) => ({ role: item.role, content: item.content })),
      },
      {
        onMeta: (meta) => {
          if (meta.session_id) mascotStore.setSessionId(meta.session_id)
          if (meta.invoked_skills?.length) assistantMsg.invokedSkills = meta.invoked_skills
          if (meta.emotion_care) {
            receivedCare = true
            emotionCare.value = meta.emotion_care
            mascotStore.triggerComfort('抱抱你，恋恋先给你倒杯热可可~', 5600)
          }
        },
        onDelta: (chunk) => {
          parser.feed(chunk)
        },
        onDone: (sid) => {
          parser.flush()
          if (sid) mascotStore.setSessionId(sid)
          mascotStore.setSpeaking(false)
          if (!assistantMsg.toolCard) {
            assistantMsg.actionHint = inferActionHint(text, assistantMsg.content)
          }
          if (!receivedCare && !receivedEmoTag) {
            mascotStore.triggerHappy(undefined, 2200)
          }
          void mascotStore.hydrateFromBackend(false)
          scrollToBottom()
        },
        onError: (errText) => {
          parser.flush()
          mascotStore.setSpeaking(false)
          if (!assistantMsg.content) {
            assistantMsg.content = `哎呀，恋恋刚才走神了一小下：${errText || '连接超时了，再试一次吧~'}`
          }
          mascotStore.setMood('comfort')
        },
      },
      abortController.signal,
    )
  } catch (err) {
    parser.flush()
    mascotStore.setSpeaking(false)
    if ((err as Error)?.name !== 'AbortError') {
      const msgText = err instanceof Error ? err.message : '网络开小差了，稍后再试试吧~'
      if (!assistantMsg.content) {
        assistantMsg.content = `抱歉呀，刚刚信号晃了一下：${msgText}`
      }
      mascotStore.setMood('comfort')
    }
  } finally {
    sending.value = false
    mascotStore.setSpeaking(false)
    abortController = null
    scrollToBottom()
  }
}

function handleComposerKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void sendPrompt()
  }
}

watch(
  () => route.path,
  (path) => {
    window.setTimeout(() => {
      mascotStore.greetByRoute(path)
    }, 650)
  },
  { immediate: true },
)

watch(
  () => mascotStore.drawerOpen,
  (isOpen) => {
    if (isOpen) {
      void loadCallableSkills()
      void mascotStore.hydrateFromBackend(false)
    } else {
      showMemories.value = false
    }
  },
)

onMounted(() => {
  window.addEventListener('resize', updateViewport)
  window.addEventListener('pointermove', handleGlobalPointerMove, { passive: true })
  void mascotStore.hydrateFromBackend(true)
  autonomousTimer = window.setInterval(() => {
    mascotStore.tickAutonomous(route.path)
  }, 9500)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
  window.removeEventListener('pointermove', handleGlobalPointerMove)
  clearLongPress()
  stopBreathing()
  if (autonomousTimer !== null) window.clearInterval(autonomousTimer)
  if (abortController) abortController.abort()
  if (bounceTimer !== null) window.clearTimeout(bounceTimer)
})
</script>

<template>
  <div class="mascot-root">
    <!-- Edge-Peek Minimized Mode (探头偷看) -->
    <div
      v-if="mascotStore.minimized"
      class="mascot-edge-peek"
      :class="`dock-${mascotStore.dockSide}`"
      :style="minimizedStyle"
      title="点一下耳朵叫出恋恋~"
      @click="onEdgePeekClick"
    >
      <transition name="bubble-pop">
        <div
          v-if="mascotStore.bubbleText"
          class="mascot-speech-bubble peek-bubble"
          :class="`side-${mascotStore.dockSide}`"
          @click.stop="mascotStore.openDrawer()"
        >
          <span>{{ mascotStore.bubbleText }}</span>
          <button type="button" class="bubble-close" @click.stop="mascotStore.dismissBubble()">×</button>
        </div>
      </transition>
      <div class="peek-head-clip">
        <MascotLianFigure
          :mood="mascotStore.mood"
          :size="68"
          :gaze-x="gazeX"
          :gaze-y="gazeY"
          :blush-opacity="mascotStore.motionParams.blushOpacity"
        />
      </div>
    </div>

    <!-- Draggable Interactive Floating Mascot -->
    <div
      v-else
      class="mascot-floating-anchor"
      :style="avatarStyle"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <!-- Greeting / Reaction Bubble -->
      <transition name="bubble-pop">
        <div
          v-if="mascotStore.bubbleText && !mascotStore.drawerOpen"
          class="mascot-speech-bubble"
          :class="`side-${mascotStore.dockSide}`"
          @pointerdown.stop
          @click.stop="mascotStore.openDrawer()"
        >
          <span>{{ mascotStore.bubbleText }}</span>
          <button
            type="button"
            class="bubble-close"
            aria-label="关闭气泡"
            @click.stop="mascotStore.dismissBubble()"
          >
            ×
          </button>
        </div>
      </transition>

      <!-- Burst Particles -->
      <span
        v-for="p in burstParticles"
        :key="p.id"
        class="burst-heart"
        :style="{ '--dx': `${p.dx}px`, '--dy': `${p.dy}px`, '--sc': p.scale }"
      >
        {{ p.symbol }}
      </span>

      <div
        class="mascot-badge-trigger"
        title="摸头/戳脸/揪耳朵/长按抱抱都有不同反应哦~ 点身体打开恋恋舱"
      >
        <MascotLianFigure
          :mood="mascotStore.mood"
          :speaking="mascotStore.speaking"
          :mouth-openness="mascotStore.mouthOpenness"
          :size="104"
          :bouncing="bouncing"
          :gaze-x="gazeX"
          :gaze-y="gazeY"
          :drag-tilt-deg="dragTiltDeg"
          :blush-opacity="mascotStore.motionParams.blushOpacity"
          :tail-freq-hz="mascotStore.motionParams.tailFreqHz"
          :tail-amp-deg="mascotStore.motionParams.tailAmpDeg"
          :breath-amp-px="mascotStore.motionParams.breathAmpPx"
          :action-pulse="mascotStore.actionPulse"
          :action-seq="mascotStore.actionSeq"
        />
        <span class="mascot-name-tag">
          <span class="status-dot" :class="`mood-${mascotStore.mood}`" />
          <span>恋恋</span>
          <span class="lv-chip">Lv.{{ mascotStore.bondLevel }}</span>
        </span>
      </div>
    </div>

    <!-- Glassmorphic Smart QA Cabin 2.0 -->
    <transition name="cabin-slide">
      <section
        v-if="mascotStore.drawerOpen && !mascotStore.minimized"
        class="mascot-cabin"
        :style="cabinPositionStyle"
        @pointerdown.stop
      >
        <header class="cabin-header">
          <div class="cabin-identity">
            <div class="cabin-mini-avatar">
              <MascotLianFigure
                :mood="mascotStore.mood"
                :speaking="mascotStore.speaking"
                :mouth-openness="mascotStore.mouthOpenness"
                :size="50"
                :blush-opacity="mascotStore.motionParams.blushOpacity"
                :tail-freq-hz="mascotStore.motionParams.tailFreqHz"
              />
            </div>
            <div class="cabin-title-block">
              <div class="cabin-title-row">
                <span class="cabin-name">恋恋</span>
                <span class="bond-pill">Lv.{{ mascotStore.bondLevel }} {{ mascotStore.bondTitle }}</span>
                <span class="cabin-mood-pill">{{ mascotStore.moodLabel }}</span>
              </div>
              <div class="affinity-track" :title="`亲密羁绊 ${mascotStore.pad.affinity}/100`">
                <div class="affinity-fill" :style="{ width: `${affinityProgress}%` }" />
              </div>
            </div>
          </div>

          <div class="cabin-header-actions">
            <button
              type="button"
              class="cabin-mem-btn"
              :class="{ 'is-active': showMemories }"
              title="查看恋恋记住的心事"
              @click="showMemories = !showMemories"
            >
              🧠 {{ mascotStore.memories.length }}
            </button>
            <el-tooltip content="新话题" placement="top">
              <el-button link class="cabin-icon-btn" @click="handleNewTopic">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="贴边探头" placement="top">
              <button type="button" class="cabin-min-btn" @click="mascotStore.setMinimized(true)">
                —
              </button>
            </el-tooltip>
            <el-tooltip content="收起窗口" placement="top">
              <el-button link class="cabin-icon-btn" @click="mascotStore.closeDrawer()">
                <el-icon><Close /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
        </header>

        <!-- Memory Inspector Panel (Ebbinghaus Episodic Memories) -->
        <div v-if="showMemories" class="memory-drawer">
          <div class="memory-drawer-head">
            <span>🧠 恋恋记住的近期心事（艾宾浩斯动态强化）</span>
            <button type="button" class="mem-close" @click="showMemories = false">收起</button>
          </div>
          <div v-if="mascotStore.memories.length === 0" class="memory-empty">
            还没有专属记忆哦，和我多聊几次心事，我会悄悄记住你们的偏好和重要时刻~
          </div>
          <div v-else class="memory-list">
            <div v-for="m in mascotStore.memories" :key="m.id" class="memory-item">
              <div class="memory-main">
                <span class="memory-cat">{{ m.category }}</span>
                <span class="memory-txt">{{ m.summary }}</span>
              </div>
              <button type="button" class="memory-del" title="忘掉这条" @click="handleForgetMemory(m.id)">
                ×
              </button>
            </div>
          </div>
        </div>

        <!-- Interactive 4-4-4 Calm Breathing Overlay -->
        <div v-if="breathingActive" class="breathing-card">
          <div class="breathing-orb" :style="{ transform: `scale(${breathingScale})` }">
            <span>{{ breathingPhase }}</span>
          </div>
          <div class="breathing-meta">
            <span>和恋恋一起慢呼吸 · 剩余 {{ breathingRemainSec }}s</span>
            <button type="button" class="breathing-stop" @click="stopBreathing">结束</button>
          </div>
        </div>

        <div ref="chatScrollRef" class="cabin-body">
          <!-- Daily Mood Check-in Strip -->
          <div v-if="mascotStore.needMoodCheckin" class="checkin-bar">
            <span class="checkin-title">今天心情怎么样？点一下告诉我</span>
            <div class="checkin-emojis">
              <button
                v-for="item in MOOD_CHOICES"
                :key="item.score"
                type="button"
                class="checkin-btn"
                :disabled="checkingIn"
                @click="handleMoodCheckin(item.score)"
              >
                <span class="ci-emoji">{{ item.emoji }}</span>
                <span class="ci-label">{{ item.label }}</span>
              </button>
            </div>
          </div>

          <!-- Knowledge Skill Bar -->
          <div v-if="callableSkills.length > 0" class="cabin-skill-bar">
            <span class="skill-bar-label">🧩 知识库：</span>
            <button
              type="button"
              class="skill-pill"
              :class="{ 'is-active': selectedSkillId === null }"
              @click="selectedSkillId = null"
            >
              自动匹配
            </button>
            <button
              v-for="sk in callableSkills.slice(0, 6)"
              :key="sk.id"
              type="button"
              class="skill-pill"
              :class="{ 'is-active': selectedSkillId === sk.id }"
              @click="selectedSkillId = selectedSkillId === sk.id ? null : sk.id"
            >
              {{ sk.name }}
            </button>
          </div>

          <!-- Warm Emotion Guardrail Card -->
          <div v-if="emotionCare" class="cabin-care-card">
            <div class="care-title">💗 {{ emotionCare.title }}</div>
            <p class="care-desc">{{ emotionCare.message }}</p>
            <div v-if="emotionCare.hotlines?.length" class="care-hotlines">
              <span v-for="item in emotionCare.hotlines" :key="item.name" class="hotline-pill">
                {{ item.name }}：{{ item.phone }}
              </span>
            </div>
          </div>

          <!-- Empty State + Quick Chips -->
          <div v-if="messages.length === 0" class="cabin-empty">
            <div class="empty-greeting">
              <div class="empty-badge">
                <el-icon><MagicStick /></el-icon>
                <span>恋恋 2.0 情感大脑已唤醒</span>
              </div>
              <p class="empty-text">
                嗨~ 摸我的头、戳我脸颊、长按抱抱我都会有不同反应哦！聊到心事我还会帮你<strong>一键带入工具</strong>或<strong>顺手记进情感档案</strong>~
              </p>
            </div>

            <div class="quick-prompts">
              <button
                v-for="q in QUICK_PROMPTS"
                :key="q"
                type="button"
                class="quick-chip"
                @click="sendPrompt(q)"
              >
                {{ q }}
              </button>
            </div>
          </div>

          <!-- Conversation Bubbles -->
          <div v-else class="cabin-messages">
            <div v-for="msg in messages" :key="msg.id" class="msg-row" :class="`is-${msg.role}`">
              <div class="msg-bubble">
                <template v-if="msg.content">
                  <div v-for="(line, lineIdx) in msg.content.split('\n')" :key="lineIdx" class="msg-line">
                    <br v-if="line.length === 0" />
                    <template v-else>
                      <template v-for="(seg, segIdx) in parseLineSegments(line)" :key="segIdx">
                        <strong v-if="seg.bold">{{ seg.text }}</strong>
                        <span v-else>{{ seg.text }}</span>
                      </template>
                    </template>
                  </div>
                </template>
                <span v-else class="typing-dots">恋恋正在竖起耳朵认真想...</span>
              </div>

              <!-- Structured Tool Execution Card -->
              <div v-if="msg.toolCard" class="tool-exec-card">
                <div class="tool-exec-info">
                  <span class="tool-exec-tag">✨ 恋恋行动建议</span>
                  <span v-if="msg.toolCard.summary" class="tool-exec-sub">{{ msg.toolCard.summary }}</span>
                </div>
                <button
                  type="button"
                  class="tool-exec-btn"
                  :class="{ 'is-done': msg.toolApplied }"
                  @click="handleExecuteToolCard(msg)"
                >
                  <span>{{ msg.toolApplied ? '已记入档案 ✓' : msg.toolCard.label }}</span>
                  <el-icon v-if="!msg.toolApplied"><Right /></el-icon>
                </button>
              </div>

              <!-- Invoked Knowledge Skill Citations -->
              <div v-if="msg.invokedSkills?.length" class="cabin-skill-cites">
                <span v-for="sk in msg.invokedSkills" :key="sk.id" class="skill-cite-tag">
                  📚 {{ sk.name }}：{{ sk.citations.map((c) => c.title).slice(0, 3).join(' · ') || '已命中' }}
                </span>
              </div>

              <!-- Assistant Actions -->
              <div v-if="msg.role === 'assistant' && msg.content && !sending" class="msg-actions">
                <button
                  type="button"
                  class="msg-action-btn"
                  :class="{ 'is-done': msg.favorited }"
                  @click="handleFavorite(msg)"
                >
                  <el-icon v-if="msg.favorited"><Check /></el-icon>
                  <el-icon v-else><Plus /></el-icon>
                  <span>{{ msg.favorited ? '已收藏' : '存金句' }}</span>
                </button>
                <button
                  v-if="msg.actionHint"
                  type="button"
                  class="msg-action-btn is-nav"
                  @click="handleNavigate(msg.actionHint.path)"
                >
                  <span>{{ msg.actionHint.label }}</span>
                  <el-icon><Right /></el-icon>
                </button>
              </div>
            </div>
          </div>
        </div>

        <footer class="cabin-footer">
          <div class="composer-box">
            <textarea
              v-model="inputText"
              class="composer-input"
              rows="2"
              placeholder="对恋恋说说心事，或贴一句 TA 的话..."
              @keydown="handleComposerKeydown"
            />
            <button
              type="button"
              class="composer-send-btn"
              :disabled="!inputText.trim() || sending"
              @click="sendPrompt()"
            >
              {{ sending ? '...' : '发送' }}
            </button>
          </div>
          <div class="cabin-footer-bar">
            <span class="footer-tip">摸头 / 戳脸 / 长按抱抱 · 拖动停靠</span>
            <button type="button" class="workbench-link" @click="handleNavigate('/ai-playground', true)">
              <el-icon><ChatDotRound /></el-icon>
              <span>转 AI 调试台深聊</span>
            </button>
          </div>
        </footer>
      </section>
    </transition>
  </div>
</template>

<style scoped>
.mascot-root {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 2100;
}

.mascot-floating-anchor,
.mascot-edge-peek,
.mascot-cabin {
  pointer-events: auto;
}

.mascot-edge-peek {
  position: fixed;
  width: 56px;
  height: 66px;
  cursor: pointer;
  z-index: 2105;
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}

.mascot-edge-peek.dock-right {
  transform: translateX(14px) rotate(-14deg);
}

.mascot-edge-peek.dock-right:hover {
  transform: translateX(-4px) rotate(-6deg);
}

.mascot-edge-peek.dock-left {
  transform: translateX(-14px) rotate(14deg);
}

.mascot-edge-peek.dock-left:hover {
  transform: translateX(4px) rotate(6deg);
}

.peek-head-clip {
  width: 64px;
  height: 64px;
  overflow: hidden;
  border-radius: 50%;
  background: rgba(255, 245, 248, 0.94);
  border: 1.5px solid rgba(200, 53, 83, 0.28);
  box-shadow: 0 8px 20px rgba(173, 45, 92, 0.22);
  display: flex;
  justify-content: center;
  padding-top: 2px;
}

.mascot-floating-anchor {
  position: fixed;
  width: 104px;
  height: 116px;
  cursor: grab;
  touch-action: none;
  user-select: none;
}

.mascot-floating-anchor:active {
  cursor: grabbing;
}

.mascot-badge-trigger {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  transition: transform 0.2s ease;
}

.mascot-badge-trigger:hover {
  transform: translateY(-2px);
}

.mascot-name-tag {
  margin-top: -10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(200, 53, 83, 0.24);
  box-shadow: 0 4px 12px rgba(200, 53, 83, 0.14);
  font-size: 11px;
  font-weight: 700;
  color: #8f234c;
}

.lv-chip {
  font-size: 10px;
  padding: 0 5px;
  border-radius: 999px;
  background: #ffe6ef;
  color: #c83553;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
}

.status-dot.mood-thinking,
.status-dot.mood-curious {
  background: #f59e0b;
}

.status-dot.mood-happy,
.status-dot.mood-excited,
.status-dot.mood-shy {
  background: #ec4899;
}

.status-dot.mood-comfort,
.status-dot.mood-pout {
  background: #fb7185;
}

.status-dot.mood-sleepy {
  background: #8b5cf6;
}

.status-dot.mood-dizzy {
  background: #eab308;
}

.mascot-speech-bubble {
  position: absolute;
  bottom: 114px;
  width: 224px;
  padding: 10px 26px 10px 12px;
  border-radius: 16px;
  background: rgba(255, 250, 252, 0.97);
  border: 1px solid rgba(200, 53, 83, 0.24);
  box-shadow: 0 10px 26px rgba(173, 45, 92, 0.16);
  font-size: 12.5px;
  line-height: 1.5;
  color: #6b223d;
  cursor: pointer;
}

.peek-bubble {
  bottom: 72px;
  transform: rotate(10deg);
}

.mascot-speech-bubble.side-right {
  right: 4px;
  border-bottom-right-radius: 4px;
}

.mascot-speech-bubble.side-left {
  left: 4px;
  border-bottom-left-radius: 4px;
}

.bubble-close {
  position: absolute;
  top: 4px;
  right: 7px;
  border: none;
  background: transparent;
  color: #b46a84;
  font-size: 15px;
  cursor: pointer;
}

.burst-heart {
  position: absolute;
  left: 46px;
  top: 34px;
  font-size: 16px;
  color: #ff4f8b;
  pointer-events: none;
  animation: burst-fly 0.9s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
}

@keyframes burst-fly {
  0% {
    opacity: 0;
    transform: translate(0, 0) scale(0.5);
  }
  20% {
    opacity: 1;
  }
  100% {
    opacity: 0;
    transform: translate(var(--dx), var(--dy)) scale(var(--sc));
  }
}

.mascot-cabin {
  position: fixed;
  display: flex;
  flex-direction: column;
  background: rgba(255, 250, 252, 0.97);
  backdrop-filter: blur(18px);
  border: 1px solid rgba(200, 53, 83, 0.18);
  border-radius: 22px;
  box-shadow: 0 18px 46px rgba(92, 22, 50, 0.2);
  overflow: hidden;
}

.cabin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  background: linear-gradient(135deg, #fff1f6 0%, #ffe6ef 100%);
  border-bottom: 1px solid rgba(200, 53, 83, 0.12);
}

.cabin-identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.cabin-mini-avatar {
  width: 50px;
  height: 54px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid rgba(200, 53, 83, 0.16);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.cabin-title-block {
  min-width: 0;
  flex: 1;
}

.cabin-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  margin-bottom: 5px;
}

.cabin-name {
  font-size: 14px;
  font-weight: 700;
  color: #6b1d3b;
}

.bond-pill {
  font-size: 10.5px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 999px;
  background: linear-gradient(135deg, #ff7aa6, #c83553);
  color: #ffffff;
}

.cabin-mood-pill {
  font-size: 10.5px;
  padding: 1px 7px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: #b8294b;
  border: 1px solid rgba(200, 53, 83, 0.18);
}

.affinity-track {
  height: 5px;
  border-radius: 999px;
  background: rgba(200, 53, 83, 0.14);
  overflow: hidden;
}

.affinity-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #ff7aa6, #c83553);
  transition: width 0.4s ease;
}

.cabin-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.cabin-mem-btn {
  border: 1px solid rgba(200, 53, 83, 0.22);
  background: rgba(255, 255, 255, 0.88);
  color: #8f234c;
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 999px;
  cursor: pointer;
}

.cabin-mem-btn.is-active {
  background: #c83553;
  color: #ffffff;
}

.cabin-icon-btn,
.cabin-min-btn {
  color: #8f4763;
  cursor: pointer;
  border: none;
  background: transparent;
  font-size: 14px;
  padding: 4px 6px;
}

.memory-drawer {
  padding: 10px 14px;
  background: #fff4f8;
  border-bottom: 1px solid rgba(200, 53, 83, 0.14);
  max-height: 155px;
  overflow-y: auto;
}

.memory-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11.5px;
  font-weight: 600;
  color: #8f234c;
  margin-bottom: 8px;
}

.mem-close {
  border: none;
  background: transparent;
  color: #c83553;
  font-size: 11.5px;
  cursor: pointer;
}

.memory-empty {
  font-size: 12px;
  color: #9e5872;
}

.memory-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.memory-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 8px;
  border-radius: 10px;
  background: #ffffff;
  border: 1px solid rgba(200, 53, 83, 0.14);
}

.memory-main {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 11.5px;
  color: #5c2a3e;
}

.memory-cat {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 999px;
  background: #ffe8ef;
  color: #c83553;
  flex-shrink: 0;
}

.memory-txt {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.memory-del {
  border: none;
  background: transparent;
  color: #b46a84;
  cursor: pointer;
  font-size: 14px;
}

.breathing-card {
  padding: 14px;
  background: linear-gradient(135deg, #fff0f6 0%, #f0f9ff 100%);
  border-bottom: 1px solid rgba(200, 53, 83, 0.14);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.breathing-orb {
  width: 78px;
  height: 78px;
  border-radius: 50%;
  background: radial-gradient(circle, #ff9ec0 0%, #e14d7c 100%);
  color: #ffffff;
  font-size: 11.5px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 0 24px rgba(236, 72, 153, 0.36);
  transition: transform 3.8s ease-in-out;
}

.breathing-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: #7f294b;
}

.breathing-stop {
  border: 1px solid rgba(200, 53, 83, 0.25);
  background: #ffffff;
  color: #c83553;
  font-size: 11px;
  padding: 2px 10px;
  border-radius: 999px;
  cursor: pointer;
}

.cabin-body {
  flex: 1;
  min-height: 220px;
  max-height: 360px;
  overflow-y: auto;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.checkin-bar {
  padding: 9px 11px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px solid rgba(200, 53, 83, 0.16);
}

.checkin-title {
  display: block;
  font-size: 11.5px;
  font-weight: 600;
  color: #8f234c;
  margin-bottom: 7px;
}

.checkin-emojis {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}

.checkin-btn {
  border: 1px solid #f5dbe4;
  background: #fff9fb;
  border-radius: 10px;
  padding: 5px 2px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease;
}

.checkin-btn:hover {
  transform: translateY(-2px);
  border-color: #d84361;
  background: #fff0f5;
}

.ci-emoji {
  font-size: 16px;
}

.ci-label {
  font-size: 10px;
  color: #6b3b50;
}

.cabin-skill-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.skill-bar-label {
  font-size: 11.5px;
  color: #8f4763;
  font-weight: 600;
}

.skill-pill {
  border: 1px solid rgba(22, 163, 74, 0.25);
  background: #f0fdf4;
  color: #166534;
  font-size: 11px;
  padding: 2px 9px;
  border-radius: 999px;
  cursor: pointer;
}

.skill-pill.is-active {
  background: #16a34a;
  color: #ffffff;
  border-color: #16a34a;
}

.cabin-care-card {
  padding: 10px 12px;
  border-radius: 14px;
  background: #fff1f5;
  border: 1px solid rgba(244, 63, 94, 0.25);
}

.care-title {
  font-size: 12.5px;
  font-weight: 700;
  color: #b91c4a;
  margin-bottom: 4px;
}

.care-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: #7c2d48;
}

.care-hotlines {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.hotline-pill {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #ffffff;
  color: #9f1239;
}

.cabin-empty {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.empty-greeting {
  padding: 12px;
  border-radius: 14px;
  background: #ffffff;
  border: 1px dashed rgba(200, 53, 83, 0.3);
}

.empty-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 700;
  color: #c83553;
  margin-bottom: 6px;
}

.empty-text {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: #5c2a3e;
}

.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.quick-chip {
  border: 1px solid rgba(200, 53, 83, 0.2);
  background: #ffffff;
  color: #7f294b;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 12px;
  cursor: pointer;
  text-align: left;
}

.quick-chip:hover {
  background: #fff2f6;
  border-color: #d84361;
}

.cabin-messages {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.msg-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.msg-row.is-user {
  align-items: flex-end;
}

.msg-row.is-assistant {
  align-items: flex-start;
}

.msg-bubble {
  max-width: 88%;
  padding: 9px 12px;
  border-radius: 15px;
  font-size: 13px;
  line-height: 1.58;
  word-break: break-word;
}

.msg-row.is-user .msg-bubble {
  background: linear-gradient(135deg, #ff6b9b, #c83553);
  color: #ffffff;
  border-bottom-right-radius: 4px;
}

.msg-row.is-assistant .msg-bubble {
  background: #ffffff;
  color: #4f2134;
  border: 1px solid rgba(200, 53, 83, 0.14);
  border-bottom-left-radius: 4px;
}

.typing-dots {
  color: #a66a81;
  font-size: 12px;
}

.tool-exec-card {
  max-width: 88%;
  padding: 8px 11px;
  border-radius: 13px;
  background: linear-gradient(135deg, #fff5f8 0%, #fffaf2 100%);
  border: 1px solid rgba(200, 53, 83, 0.25);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.tool-exec-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tool-exec-tag {
  font-size: 10.5px;
  font-weight: 700;
  color: #c83553;
}

.tool-exec-sub {
  font-size: 11.5px;
  color: #6b3b50;
}

.tool-exec-btn {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #ff6b9b, #c83553);
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.tool-exec-btn.is-done {
  background: #16a34a;
}

.cabin-skill-cites {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.skill-cite-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
}

.msg-actions {
  display: flex;
  gap: 6px;
}

.msg-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid rgba(200, 53, 83, 0.2);
  background: #ffffff;
  color: #8f234c;
  font-size: 11px;
  cursor: pointer;
}

.msg-action-btn.is-done {
  background: #f0fdf4;
  border-color: #86efac;
  color: #15803d;
}

.msg-action-btn.is-nav {
  background: #fff2f6;
  color: #c83553;
}

.cabin-footer {
  padding: 10px 12px;
  background: #ffffff;
  border-top: 1px solid #f3dfe5;
}

.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.composer-input {
  flex: 1;
  border: 1px solid rgba(200, 53, 83, 0.22);
  border-radius: 14px;
  background: #fff8fa;
  padding: 7px 10px;
  font-size: 12.5px;
  resize: none;
  outline: none;
  color: #3f1829;
  font-family: inherit;
}

.composer-send-btn {
  height: 36px;
  padding: 0 14px;
  border-radius: 999px;
  border: none;
  background: linear-gradient(135deg, #ff6b9b, #c83553);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  flex-shrink: 0;
}

.composer-send-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.cabin-footer-bar {
  margin-top: 7px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: #a86b82;
}

.workbench-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: #c83553;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
}

.bubble-pop-enter-active,
.bubble-pop-leave-active,
.cabin-slide-enter-active,
.cabin-slide-leave-active {
  transition: all 0.22s cubic-bezier(0.22, 1, 0.36, 1);
}

.bubble-pop-enter-from,
.bubble-pop-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.92);
}

.cabin-slide-enter-from,
.cabin-slide-leave-to {
  opacity: 0;
  transform: translateY(10px) scale(0.96);
}
</style>
