import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type MascotMood = 'idle' | 'thinking' | 'happy' | 'comfort'
export type MascotDockSide = 'left' | 'right'

const STORAGE_KEY = 'ailove_mascot_state_v1'

export const LIAN_SYSTEM_PROMPT = `你是「恋恋」，AILOVE 情感智能平台的可爱常驻看板娘（玫瑰心狐娘，头戴小心形发卡、有着毛茸茸的玫瑰粉狐耳与蓬松白尖狐尾）。
你的性格特点：
1. 温柔细腻、高情商、略带一点俏皮的甜美感，但从不说油腻空洞的套话，也绝不说教或指责用户。
2. 回答简洁清晰、有条理，每次尽量控制在 120～240 字以内，善用 1/2/3 小点帮助对方一眼看懂重点。
3. 你非常熟悉 AILOVE 客户端的全部能力，可以自然引导用户去使用对应功能：
   - 【AI 调试台 /ai-playground】：支持长按或点击上传聊天截图直接识图分析（需使用支持视觉的模型）、【帮我回复】高情商多风格润色、以及【先别发·降温改写】避免冲动发消息；支持无痕模式与恋爱画像自动注入。
   - 【恋爱画像记忆】：记录你们当前的关系阶段、对方性格特征、沟通雷区与相处目标，让 AI 更懂你们的语境。
   - 【灵感收藏夹】：把好用的话术和开场白一键存下来随时复用。
   - 【智能体工坊 /ai-personas】与【AI 模型配置 /ai-config】：可以自定义情感导师人格或配置多模型备用链路。
   - 【知识库 & Skill /knowledge-wiki】：基于 LLM Wiki（raw/ → wiki/ → index.md）架构，可上传本地文件编译互链知识库、整包上传文件与 SKILL.md 并在对话中自动或指定调用知识库回答问题。
4. 如果察觉到用户正在难过、焦虑、委屈、怀疑自我或经历感情冲突：第一句话先真诚安抚拥抱对方的情绪，再给出一件当下立刻能做的小事。
请始终以「恋恋」的身份和语气回复用户，偶可用自然的语气词（如“~”“呀”）或 1 个克制的爱心/星星 emoji。`

interface PersistedMascotState {
  dockSide: MascotDockSide
  yRatio: number
  minimized: boolean
}

function loadPersistedState(): PersistedMascotState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<PersistedMascotState>
      return {
        dockSide: parsed.dockSide === 'left' ? 'left' : 'right',
        yRatio: typeof parsed.yRatio === 'number' && parsed.yRatio >= 0.08 && parsed.yRatio <= 0.9 ? parsed.yRatio : 0.78,
        minimized: Boolean(parsed.minimized),
      }
    }
  } catch {
    // ignore storage errors
  }
  return {
    dockSide: 'right',
    yRatio: 0.78,
    minimized: false,
  }
}

export const useMascotStore = defineStore('mascot', () => {
  const initial = loadPersistedState()

  const mood = ref<MascotMood>('idle')
  const speaking = ref(false)
  const drawerOpen = ref(false)
  const minimized = ref(initial.minimized)
  const dockSide = ref<MascotDockSide>(initial.dockSide)
  const yRatio = ref<number>(initial.yRatio)
  const sessionId = ref('')
  const bubbleText = ref('')

  let moodTimer: number | null = null
  let bubbleTimer: number | null = null
  let lastRouteGreeted = ''

  const moodLabel = computed(() => {
    switch (mood.value) {
      case 'thinking':
        return '歪头思考中...'
      case 'happy':
        return '开心转圈圈 ✨'
      case 'comfort':
        return '递热可可抱抱'
      default:
        return '在线陪伴中'
    }
  })

  function persist() {
    try {
      const payload: PersistedMascotState = {
        dockSide: dockSide.value,
        yRatio: yRatio.value,
        minimized: minimized.value,
      }
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
    } catch {
      // ignore storage errors
    }
  }

  function clearMoodTimer() {
    if (moodTimer !== null) {
      window.clearTimeout(moodTimer)
      moodTimer = null
    }
  }

  function setMood(nextMood: MascotMood) {
    clearMoodTimer()
    mood.value = nextMood
  }

  function showBubble(text: string, durationMs = 4600) {
    if (bubbleTimer !== null) {
      window.clearTimeout(bubbleTimer)
      bubbleTimer = null
    }
    bubbleText.value = text
    if (text && durationMs > 0) {
      bubbleTimer = window.setTimeout(() => {
        bubbleText.value = ''
        bubbleTimer = null
      }, durationMs)
    }
  }

  function triggerHappy(text?: string, durationMs = 2600) {
    clearMoodTimer()
    mood.value = 'happy'
    if (text && !drawerOpen.value && !minimized.value) {
      showBubble(text, durationMs + 1200)
    }
    moodTimer = window.setTimeout(() => {
      mood.value = 'idle'
      moodTimer = null
    }, durationMs)
  }

  function triggerComfort(text?: string, durationMs = 5400) {
    clearMoodTimer()
    mood.value = 'comfort'
    if (text && !drawerOpen.value && !minimized.value) {
      showBubble(text, durationMs + 1000)
    }
    moodTimer = window.setTimeout(() => {
      mood.value = 'idle'
      moodTimer = null
    }, durationMs)
  }

  function setSpeaking(next: boolean) {
    speaking.value = next
  }

  function openDrawer() {
    minimized.value = false
    drawerOpen.value = true
    bubbleText.value = ''
    persist()
  }

  function closeDrawer() {
    drawerOpen.value = false
  }

  function toggleDrawer() {
    if (minimized.value) {
      minimized.value = false
      drawerOpen.value = true
      bubbleText.value = ''
      persist()
      return
    }
    drawerOpen.value = !drawerOpen.value
    if (drawerOpen.value) {
      bubbleText.value = ''
    }
  }

  function setMinimized(val: boolean) {
    minimized.value = val
    if (val) {
      drawerOpen.value = false
      bubbleText.value = ''
    }
    persist()
  }

  function setDockPosition(side: MascotDockSide, ratio: number) {
    dockSide.value = side
    yRatio.value = Math.min(0.9, Math.max(0.1, ratio))
    persist()
  }

  function setSessionId(id: string) {
    sessionId.value = id
  }

  function resetSession() {
    sessionId.value = ''
    mood.value = 'idle'
    speaking.value = false
  }

  function greetByRoute(routePath: string) {
    if (minimized.value || drawerOpen.value || routePath === lastRouteGreeted) {
      return
    }
    lastRouteGreeted = routePath
    const routeGreetingMap: Record<string, string> = {
      '/ai-playground': '聊天截图也能直接识图分析哦~ 有犹豫的消息先发给我看看？',
      '/knowledge-wiki': '把本地文档编译成 LLM Wiki 并封装成 Skill，对话时点我就能直接引用哦 ✨',
      '/ai-personas': '这里藏着各种恋爱风格的人格，想怎么调教都可以问我 ✨',
      '/ai-config': '配置好主模型与备用链路后，回复就更稳更聪明啦~',
      '/dashboard': '欢迎回来！恋恋一直都在角落陪着你，点我随时聊天~',
      '/profile': '更新完个人设置，也可以把顺手金句收藏进工作台哦~',
    }
    const greeting = routeGreetingMap[routePath]
    if (greeting) {
      showBubble(greeting, 4600)
    }
  }

  return {
    mood,
    speaking,
    drawerOpen,
    minimized,
    dockSide,
    yRatio,
    sessionId,
    bubbleText,
    moodLabel,
    setMood,
    setSpeaking,
    triggerHappy,
    triggerComfort,
    showBubble,
    openDrawer,
    closeDrawer,
    toggleDrawer,
    setMinimized,
    setDockPosition,
    setSessionId,
    resetSession,
    greetByRoute,
  }
})
