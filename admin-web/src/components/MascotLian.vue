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
} from '@/api/ai'
import MascotLianFigure from '@/components/MascotLianFigure.vue'
import { LIAN_SYSTEM_PROMPT, useMascotStore } from '@/stores/mascot'

interface CabinMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  favorited?: boolean
  actionHint?: {
    label: string
    path: string
  } | null
}

interface BurstHeart {
  id: number
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
  '聊天截图怎么直接识图？',
  'Ta 已读不回怎么高情商破冰？',
  '好生气想发长文，怎么用先别发降温？',
  '恋爱画像填哪些信息AI会更懂我？',
]

const route = useRoute()
const router = useRouter()
const mascotStore = useMascotStore()

const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const viewportHeight = ref(typeof window !== 'undefined' ? window.innerHeight : 800)

// Dragging state
const isDragging = ref(false)
const hasMoved = ref(false)
const dragX = ref(0)
const dragY = ref(0)
const pointerStartX = ref(0)
const pointerStartY = ref(0)
const avatarStartX = ref(0)
const avatarStartY = ref(0)

// Playful feedback
const bouncing = ref(false)
const burstHearts = ref<BurstHeart[]>([])
let bounceTimer: number | null = null
let heartIdSeq = 1

// QA Cabin state
const inputText = ref('')
const sending = ref(false)
const messages = ref<CabinMessage[]>([])
const emotionCare = ref<EmotionCareNotice | null>(null)
const chatScrollRef = ref<HTMLElement | null>(null)
let abortController: AbortController | null = null

const clampedTop = computed(() => {
  const maxTop = Math.max(72, viewportHeight.value - AVATAR_H - 18)
  const desired = mascotStore.yRatio * viewportHeight.value - AVATAR_H / 2
  return Math.min(maxTop, Math.max(72, desired))
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
  const topPx = `${Math.round(clampedTop.value + 20)}px`
  return mascotStore.dockSide === 'left'
    ? { left: '0px', right: 'auto', top: topPx }
    : { right: '0px', left: 'auto', top: topPx }
})

const cabinPositionStyle = computed(() => {
  const cabinW = Math.min(378, viewportWidth.value - 28)
  const cabinH = Math.min(526, viewportHeight.value - 88)
  const avatarX = mascotStore.dockSide === 'left'
    ? EDGE_MARGIN
    : Math.max(EDGE_MARGIN, viewportWidth.value - AVATAR_W - EDGE_MARGIN)

  let left = mascotStore.dockSide === 'right'
    ? avatarX - cabinW - 14
    : avatarX + AVATAR_W + 14

  if (left < 14) {
    left = Math.max(14, viewportWidth.value - cabinW - 14)
  }
  if (left + cabinW > viewportWidth.value - 14) {
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

function updateViewport() {
  viewportWidth.value = window.innerWidth
  viewportHeight.value = window.innerHeight
}

function triggerJellyAndHearts() {
  bouncing.value = false
  window.requestAnimationFrame(() => {
    bouncing.value = true
  })
  if (bounceTimer !== null) window.clearTimeout(bounceTimer)
  bounceTimer = window.setTimeout(() => {
    bouncing.value = false
    bounceTimer = null
  }, 560)

  const batch: BurstHeart[] = Array.from({ length: 5 }, (_, idx) => ({
    id: heartIdSeq++,
    dx: (idx - 2) * 14 + (Math.random() * 8 - 4),
    dy: -42 - Math.random() * 26,
    scale: 0.78 + Math.random() * 0.45,
  }))
  burstHearts.value = [...burstHearts.value, ...batch]
  window.setTimeout(() => {
    const removeIds = new Set(batch.map((item) => item.id))
    burstHearts.value = burstHearts.value.filter((item) => !removeIds.has(item.id))
  }, 950)
}

function onPointerDown(e: PointerEvent) {
  if (e.button !== 0) return
  const target = e.currentTarget as HTMLElement
  target.setPointerCapture(e.pointerId)
  isDragging.value = true
  hasMoved.value = false
  pointerStartX.value = e.clientX
  pointerStartY.value = e.clientY

  const currentLeft = mascotStore.dockSide === 'left'
    ? EDGE_MARGIN
    : Math.max(EDGE_MARGIN, viewportWidth.value - AVATAR_W - EDGE_MARGIN)
  avatarStartX.value = currentLeft
  avatarStartY.value = clampedTop.value
  dragX.value = currentLeft
  dragY.value = clampedTop.value
}

function onPointerMove(e: PointerEvent) {
  if (!isDragging.value) return
  const dx = e.clientX - pointerStartX.value
  const dy = e.clientY - pointerStartY.value
  if (!hasMoved.value && Math.hypot(dx, dy) > 6) {
    hasMoved.value = true
  }
  if (hasMoved.value) {
    dragX.value = Math.min(Math.max(8, avatarStartX.value + dx), Math.max(8, viewportWidth.value - AVATAR_W - 8))
    dragY.value = Math.min(Math.max(66, avatarStartY.value + dy), Math.max(66, viewportHeight.value - AVATAR_H - 12))
  }
}

function onPointerUp(e: PointerEvent) {
  if (!isDragging.value) return
  try {
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
  } catch {
    // ignore if already released
  }
  const wasDragged = hasMoved.value
  isDragging.value = false
  hasMoved.value = false

  if (wasDragged) {
    const centerX = dragX.value + AVATAR_W / 2
    const nextSide = centerX < viewportWidth.value / 2 ? 'left' : 'right'
    const nextYRatio = (dragY.value + AVATAR_H / 2) / Math.max(1, viewportHeight.value)
    mascotStore.setDockPosition(nextSide, nextYRatio)
    return
  }

  // Treated as click
  triggerJellyAndHearts()
  mascotStore.toggleDrawer()
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
  if (/智能体|人格|persona/i.test(combined)) {
    return { label: '去智能体工坊看看', path: '/ai-personas' }
  }
  if (/模型|配置|备用链路|api key/i.test(combined)) {
    return { label: '去 AI 模型配置', path: '/ai-config' }
  }
  if (/工作台|调试台|识图|截图|先别发|帮我回复|恋爱画像|收藏/i.test(combined)) {
    return { label: '去 AI 调试台试试', path: '/ai-playground' }
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

function handleNewTopic() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  sending.value = false
  messages.value = []
  emotionCare.value = null
  mascotStore.resetSession()
  mascotStore.showBubble('新话题准备好啦，想问什么都可以~', 2800)
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
    const msgText = err instanceof Error ? err.message : '收藏失败，请稍后重试'
    ElMessage.error(msgText)
  }
}

async function sendPrompt(rawText?: string) {
  const text = (rawText ?? inputText.value).trim()
  if (!text || sending.value) return

  if (!rawText) {
    inputText.value = ''
  }

  const userMsg: CabinMessage = {
    id: `u_${Date.now()}`,
    role: 'user',
    content: text,
  }
  const assistantMsg: CabinMessage = {
    id: `a_${Date.now() + 1}`,
    role: 'assistant',
    content: '',
  }

  messages.value.push(userMsg, assistantMsg)
  emotionCare.value = null
  sending.value = true
  mascotStore.setMood('thinking')
  mascotStore.setSpeaking(false)
  scrollToBottom()

  abortController = new AbortController()
  let receivedCare = false

  try {
    await streamAiChat(
      {
        message: text,
        session_id: mascotStore.sessionId || undefined,
        system_prompt: LIAN_SYSTEM_PROMPT,
        temperature: 0.75,
        use_love_profile: true,
        ephemeral_history: messages.value
          .slice(0, -2)
          .slice(-6)
          .map((item) => ({ role: item.role, content: item.content })),
      },
      {
        onMeta: (meta) => {
          if (meta.session_id) {
            mascotStore.setSessionId(meta.session_id)
          }
          if (meta.emotion_care) {
            receivedCare = true
            emotionCare.value = meta.emotion_care
            mascotStore.triggerComfort('抱抱你，恋恋先给你倒杯热可可~', 5600)
          }
        },
        onDelta: (chunk) => {
          if (!receivedCare) {
            mascotStore.setMood('idle')
          }
          mascotStore.setSpeaking(true)
          assistantMsg.content += chunk
          scrollToBottom()
        },
        onDone: (sid) => {
          if (sid) mascotStore.setSessionId(sid)
          mascotStore.setSpeaking(false)
          assistantMsg.actionHint = inferActionHint(text, assistantMsg.content)
          if (!receivedCare) {
            mascotStore.triggerHappy(undefined, 2200)
          }
          scrollToBottom()
        },
        onError: (errText) => {
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
    sendPrompt()
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

onMounted(() => {
  window.addEventListener('resize', updateViewport)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
  if (abortController) {
    abortController.abort()
  }
  if (bounceTimer !== null) {
    window.clearTimeout(bounceTimer)
  }
})
</script>

<template>
  <div class="mascot-root">
    <!-- Minimized Dock Tab -->
    <button
      v-if="mascotStore.minimized"
      type="button"
      class="mascot-minimized-pill"
      :class="`dock-${mascotStore.dockSide}`"
      :style="minimizedStyle"
      @click="mascotStore.setMinimized(false)"
    >
      <span class="mini-heart">♥</span>
      <span class="mini-label">呼唤恋恋</span>
    </button>

    <!-- Draggable Floating Mascot Badge -->
    <div
      v-else
      class="mascot-floating-anchor"
      :style="avatarStyle"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerUp"
    >
      <!-- Greeting Bubble -->
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
            @click.stop="mascotStore.showBubble('', 0)"
          >
            ×
          </button>
        </div>
      </transition>

      <!-- Floating Click Burst Hearts -->
      <span
        v-for="heart in burstHearts"
        :key="heart.id"
        class="burst-heart"
        :style="{
          '--dx': `${heart.dx}px`,
          '--dy': `${heart.dy}px`,
          '--sc': heart.scale,
        }"
      >
        ♥
      </span>

      <div class="mascot-badge-trigger" :title="mascotStore.drawerOpen ? '点我收起恋恋问答舱' : '点我找恋恋聊聊~ 也可按住拖动位置'">
        <MascotLianFigure
          :mood="mascotStore.mood"
          :speaking="mascotStore.speaking"
          :size="104"
          :bouncing="bouncing"
        />
        <span class="mascot-name-tag">
          <span class="status-dot" :class="`mood-${mascotStore.mood}`" />
          恋恋
        </span>
      </div>
    </div>

    <!-- Glassmorphic QA Cabin -->
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
                :size="50"
              />
            </div>
            <div class="cabin-title-block">
              <div class="cabin-title-row">
                <span class="cabin-name">玫瑰心狐 · 恋恋</span>
                <span class="cabin-mood-pill" :class="`mood-${mascotStore.mood}`">
                  {{ mascotStore.moodLabel }}
                </span>
              </div>
              <p class="cabin-subtitle">不懂的功能问我，心情不好也找我抱抱~</p>
            </div>
          </div>

          <div class="cabin-header-actions">
            <el-tooltip content="新话题" placement="top">
              <el-button link class="cabin-icon-btn" @click="handleNewTopic">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </el-tooltip>
            <el-tooltip content="贴边隐藏" placement="top">
              <button
                type="button"
                class="cabin-min-btn"
                @click="mascotStore.setMinimized(true)"
              >
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

        <div ref="chatScrollRef" class="cabin-body">
          <!-- Warm Emotion Guardrail Care Card -->
          <div v-if="emotionCare" class="cabin-care-card">
            <div class="care-title">💗 {{ emotionCare.title }}</div>
            <p class="care-desc">{{ emotionCare.message }}</p>
            <div v-if="emotionCare.hotlines?.length" class="care-hotlines">
              <span
                v-for="item in emotionCare.hotlines"
                :key="item.name"
                class="hotline-pill"
              >
                {{ item.name }}：{{ item.phone }}
              </span>
            </div>
          </div>

          <!-- Empty State + Quick Chips -->
          <div v-if="messages.length === 0" class="cabin-empty">
            <div class="empty-greeting">
              <div class="empty-badge">
                <el-icon><MagicStick /></el-icon>
                <span>恋恋随时待命中</span>
              </div>
              <p class="empty-text">
                嗨~ 我是住在 AILOVE 客户端里的<strong>恋恋</strong>！无论是「聊天不知道怎么接」、需要用「先别发降温」，还是找功能入口，都可以直接问我哦~
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
            <div
              v-for="msg in messages"
              :key="msg.id"
              class="msg-row"
              :class="`is-${msg.role}`"
            >
              <div class="msg-bubble">
                <template v-if="msg.content">
                  <div
                    v-for="(line, lineIdx) in msg.content.split('\n')"
                    :key="lineIdx"
                    class="msg-line"
                  >
                    <template v-if="line.length === 0">
                      <br />
                    </template>
                    <template v-else>
                      <template v-for="(seg, segIdx) in parseLineSegments(line)" :key="segIdx">
                        <strong v-if="seg.bold">{{ seg.text }}</strong>
                        <span v-else>{{ seg.text }}</span>
                      </template>
                    </template>
                  </div>
                </template>
                <span v-else class="typing-dots">恋恋正在组织甜美又靠谱的回答...</span>
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
              placeholder="问恋恋：怎么识图 / 帮我想句回复 / 抱抱我..."
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
            <span class="footer-tip">Enter 发送 · 拖拽头像可停靠左右边</span>
            <button
              type="button"
              class="workbench-link"
              @click="handleNavigate('/ai-playground', true)"
            >
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
.mascot-minimized-pill,
.mascot-cabin {
  pointer-events: auto;
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
  transform: translateY(-3px) scale(1.03);
}

.mascot-name-tag {
  margin-top: -10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(235, 95, 138, 0.28);
  box-shadow: 0 4px 12px rgba(173, 45, 92, 0.14);
  font-size: 11px;
  font-weight: 600;
  color: #8f234c;
  backdrop-filter: blur(8px);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #36c98e;
}

.status-dot.mood-thinking {
  background: #f59e0b;
  animation: dot-pulse 1s infinite;
}

.status-dot.mood-happy {
  background: #ec4899;
}

.status-dot.mood-comfort {
  background: #fb7185;
}

@keyframes dot-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.4;
    transform: scale(0.75);
  }
}

.mascot-speech-bubble {
  position: absolute;
  bottom: 84px;
  width: max-content;
  max-width: 224px;
  padding: 9px 26px 9px 12px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.97), rgba(255, 242, 247, 0.96));
  border: 1px solid rgba(235, 95, 138, 0.26);
  box-shadow: 0 10px 26px rgba(173, 45, 92, 0.16);
  color: #6b223d;
  font-size: 12.5px;
  line-height: 1.5;
  cursor: pointer;
  backdrop-filter: blur(10px);
}

.mascot-speech-bubble.side-right {
  right: 10px;
  border-bottom-right-radius: 4px;
}

.mascot-speech-bubble.side-left {
  left: 10px;
  border-bottom-left-radius: 4px;
}

.bubble-close {
  position: absolute;
  top: 4px;
  right: 6px;
  border: none;
  background: transparent;
  color: #b46a84;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
}

.bubble-close:hover {
  color: #d93f74;
}

.burst-heart {
  position: absolute;
  left: 50%;
  top: 34%;
  font-size: 14px;
  color: #ff4f8b;
  pointer-events: none;
  animation: burst-float 0.92s cubic-bezier(0.2, 0.8, 0.2, 1) forwards;
}

@keyframes burst-float {
  0% {
    opacity: 0;
    transform: translate(-50%, -50%) scale(0.4);
  }
  20% {
    opacity: 1;
  }
  100% {
    opacity: 0;
    transform: translate(calc(-50% + var(--dx)), calc(-50% + var(--dy))) scale(var(--sc));
  }
}

.mascot-minimized-pill {
  position: fixed;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 12px;
  background: linear-gradient(135deg, #ff7aa6, #e1467b);
  color: #ffffff;
  border: 1px solid rgba(255, 255, 255, 0.55);
  box-shadow: 0 8px 20px rgba(214, 58, 111, 0.28);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.mascot-minimized-pill.dock-right {
  border-radius: 999px 0 0 999px;
}

.mascot-minimized-pill.dock-left {
  border-radius: 0 999px 999px 0;
}

.mascot-minimized-pill:hover {
  transform: scale(1.04);
}

.mini-heart {
  font-size: 13px;
}

.mascot-cabin {
  position: fixed;
  display: flex;
  flex-direction: column;
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(255, 250, 252, 0.96), rgba(255, 255, 255, 0.97));
  border: 1px solid rgba(235, 95, 138, 0.22);
  box-shadow: 0 22px 48px rgba(92, 22, 50, 0.18), 0 4px 16px rgba(225, 70, 123, 0.12);
  backdrop-filter: blur(18px);
  overflow: hidden;
}

.cabin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 14px;
  background: linear-gradient(135deg, #fff1f6 0%, #ffe6ef 100%);
  border-bottom: 1px solid rgba(235, 95, 138, 0.15);
}

.cabin-identity {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.cabin-mini-avatar {
  flex-shrink: 0;
  width: 50px;
  height: 54px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(235, 95, 138, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.cabin-title-block {
  min-width: 0;
}

.cabin-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.cabin-name {
  font-size: 14px;
  font-weight: 700;
  color: #6b1d3b;
}

.cabin-mood-pill {
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.9);
  color: #be3769;
  border: 1px solid rgba(235, 95, 138, 0.22);
}

.cabin-subtitle {
  margin: 2px 0 0;
  font-size: 11.5px;
  color: #9e5872;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cabin-header-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.cabin-icon-btn,
.cabin-min-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: none;
  background: transparent;
  color: #8f4763;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 13px;
  padding: 0;
}

.cabin-icon-btn:hover,
.cabin-min-btn:hover {
  background: rgba(235, 95, 138, 0.12);
  color: #d93f74;
}

.cabin-body {
  flex: 1;
  min-height: 220px;
  max-height: 332px;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.cabin-care-card {
  padding: 10px 12px;
  border-radius: 12px;
  background: #fff3f6;
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
  margin-top: 8px;
}

.hotline-pill {
  padding: 2px 8px;
  border-radius: 999px;
  background: #ffffff;
  border: 1px solid rgba(244, 63, 94, 0.25);
  font-size: 11px;
  color: #9f1239;
}

.cabin-empty {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty-greeting {
  padding: 12px;
  border-radius: 14px;
  background: linear-gradient(135deg, #fff5f8, #fffafc);
  border: 1px dashed rgba(235, 95, 138, 0.34);
}

.empty-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 700;
  color: #d63d73;
  margin-bottom: 6px;
}

.empty-text {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: #5c2a3e;
}

.quick-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-chip {
  text-align: left;
  padding: 7px 11px;
  border-radius: 12px;
  border: 1px solid rgba(235, 95, 138, 0.22);
  background: #ffffff;
  color: #7f294b;
  font-size: 12px;
  line-height: 1.4;
  cursor: pointer;
  transition: all 0.18s ease;
}

.quick-chip:hover {
  background: #fff0f5;
  border-color: #ef6a98;
  transform: translateY(-1px);
}

.cabin-messages {
  display: flex;
  flex-direction: column;
  gap: 12px;
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
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}

.msg-row.is-user .msg-bubble {
  background: linear-gradient(135deg, #ff6d9c, #df4278);
  color: #ffffff;
  border-bottom-right-radius: 4px;
}

.msg-row.is-assistant .msg-bubble {
  background: #fff6f9;
  color: #4f2134;
  border: 1px solid rgba(235, 95, 138, 0.16);
  border-bottom-left-radius: 4px;
}

.msg-line {
  min-height: 1em;
}

.typing-dots {
  color: #a95c78;
  font-size: 12px;
}

.msg-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.msg-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid rgba(235, 95, 138, 0.24);
  background: #ffffff;
  color: #a13561;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.16s ease;
}

.msg-action-btn:hover {
  background: #fff0f5;
  border-color: #ea6190;
}

.msg-action-btn.is-done {
  color: #15803d;
  border-color: rgba(22, 163, 74, 0.3);
  background: #f0fdf4;
}

.msg-action-btn.is-nav {
  color: #d63d73;
  font-weight: 600;
}

.cabin-footer {
  padding: 10px 12px 10px;
  border-top: 1px solid rgba(235, 95, 138, 0.14);
  background: #ffffff;
}

.composer-box {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 7px 9px;
  border-radius: 13px;
  border: 1px solid rgba(235, 95, 138, 0.26);
  background: #fffafc;
}

.composer-box:focus-within {
  border-color: #ea5a8b;
  box-shadow: 0 0 0 3px rgba(234, 90, 139, 0.12);
}

.composer-input {
  flex: 1;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-family: inherit;
  font-size: 12.5px;
  line-height: 1.5;
  color: #3f1829;
  max-height: 76px;
}

.composer-send-btn {
  flex-shrink: 0;
  padding: 6px 14px;
  border-radius: 10px;
  border: none;
  background: linear-gradient(135deg, #ff6b9b, #df4278);
  color: #ffffff;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.18s ease, transform 0.15s ease;
}

.composer-send-btn:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.composer-send-btn:not(:disabled):hover {
  transform: translateY(-1px);
}

.cabin-footer-bar {
  margin-top: 7px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.footer-tip {
  font-size: 10.5px;
  color: #b4788f;
}

.workbench-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: none;
  background: transparent;
  color: #d63d73;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 4px;
}

.workbench-link:hover {
  text-decoration: underline;
}

.bubble-pop-enter-active,
.bubble-pop-leave-active {
  transition: all 0.24s cubic-bezier(0.22, 1, 0.36, 1);
}

.bubble-pop-enter-from,
.bubble-pop-leave-to {
  opacity: 0;
  transform: translateY(6px) scale(0.95);
}

.cabin-slide-enter-active,
.cabin-slide-leave-active {
  transition: all 0.24s cubic-bezier(0.22, 1, 0.36, 1);
}

.cabin-slide-enter-from,
.cabin-slide-leave-to {
  opacity: 0;
  transform: translateY(12px) scale(0.96);
}
</style>
