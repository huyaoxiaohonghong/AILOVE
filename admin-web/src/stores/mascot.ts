import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  deleteMascotMemory as apiDeleteMascotMemory,
  fetchMascotState,
  sendMascotInteract,
  submitMascotMoodCheckin,
  type MascotBackendState,
  type MascotMemoryItem,
} from '@/api/mascot'
import {
  clamp,
  computeModulatedMotionParams,
  decayPAD,
  getCircadianBaseline,
  mapPADToMood,
  MOOD_LABELS,
  UtilityBehaviorScheduler,
  type MascotChoreoAction,
  type MascotEmoDirective,
  type MascotGesture,
  type MascotMood,
  type MascotToolDirective,
  type PADVector,
} from '@/utils/mascotBrain'

export type { MascotMood }
export type MascotDockSide = 'left' | 'right'

const STORAGE_KEY = 'ailove_mascot_state_v2'

export const LIAN_SYSTEM_PROMPT = `你是「恋恋」，AILOVE 情感智能平台的可爱常驻看板娘（玫瑰心狐娘，头戴小心形发卡、有着毛茸茸的玫瑰粉狐耳与蓬松白尖狐尾）。
你的性格特点：
1. 温柔细腻、高情商、略带一点俏皮的甜美感，但从不说油腻空洞的套话，也绝不说教或指责用户。
2. 回答简洁清晰、有条理，每次尽量控制在 100～220 字以内，善用 1/2/3 小点帮助对方一眼看懂重点。
3. 你非常熟悉 AILOVE 客户端的全部能力，可以自然引导并附带工具卡片帮用户一步完成：
   - 【AI 调试台 /ai-playground】：聊天截图直接识图分析、【帮我回复】多风格高情商回复、【先别发·降温改写】避免冲动发狠话。
   - 【恋爱画像记忆】：记录关系阶段、对方性格特征、沟通雷区与相处目标。
   - 【灵感收藏夹】：一键保存好用的高情商话术。
   - 【知识库 & Skill /knowledge-wiki】：基于 LLM Wiki 架构编译本地文档并生成 Skill，在对话中自动或指定调用知识库回答问题。
4. 如果察觉到用户正在难过、焦虑、委屈或经历感情冲突：第一句话先真诚拥抱安抚对方的情绪，再给出一件当下立刻能做的小事。
请始终以「恋恋」的身份和语气回复用户，并严格遵守系统附带的 [[emo:...]] 动作编排协议。`

interface PersistedMascotState {
  dockSide: MascotDockSide
  yRatio: number
  minimized: boolean
}

function loadPersistedState(): PersistedMascotState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY) || localStorage.getItem('ailove_mascot_state_v1')
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<PersistedMascotState>
      return {
        dockSide: parsed.dockSide === 'left' ? 'left' : 'right',
        yRatio:
          typeof parsed.yRatio === 'number' && parsed.yRatio >= 0.08 && parsed.yRatio <= 0.9
            ? parsed.yRatio
            : 0.78,
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
  const baseCircadian = getCircadianBaseline()

  // Continuous PAD affective vector
  const pad = ref<PADVector>({
    valence: baseCircadian.valence,
    arousal: baseCircadian.arousal,
    affinity: 12,
  })
  const bondLevel = ref(1)
  const bondTitle = ref('初遇心狐')
  const nextLevelAffinity = ref<number | null>(20)
  const needMoodCheckin = ref(false)
  const todayMoodScore = ref(0)
  const memories = ref<MascotMemoryItem[]>([])
  const hydrated = ref(false)

  // Live animation & expression state
  const mood = ref<MascotMood>(mapPADToMood(pad.value.valence, pad.value.arousal))
  const speaking = ref(false)
  const mouthOpenness = ref(0)
  const actionPulse = ref<MascotChoreoAction>('none')
  const actionSeq = ref(0)
  const drawerOpen = ref(false)
  const minimized = ref(initial.minimized)
  const dockSide = ref<MascotDockSide>(initial.dockSide)
  const yRatio = ref<number>(initial.yRatio)
  const sessionId = ref('')
  const bubbleText = ref('')
  const pendingToolIntent = ref<MascotToolDirective | null>(null)
  const currentContextHint = ref('')

  const scheduler = new UtilityBehaviorScheduler()
  let lastActivityAt = Date.now()
  let lastDecayAt = Date.now()
  let moodTimer: number | null = null
  let bubbleTimer: number | null = null
  let mouthDecayTimer: number | null = null
  let lastRouteGreeted = ''
  let lastDraftSignalAt = 0

  const moodLabel = computed(() => MOOD_LABELS[mood.value] || '在线陪伴中')
  const motionParams = computed(() => computeModulatedMotionParams(pad.value, mood.value))

  function touchActivity() {
    lastActivityAt = Date.now()
  }

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

  function applyBackendState(st: MascotBackendState) {
    pad.value = {
      valence: clamp(Number(st.valence ?? 0.25), -1, 1),
      arousal: clamp(Number(st.arousal ?? 0.35), 0, 1),
      affinity: clamp(Number(st.affinity ?? 12), 0, 100),
    }
    bondLevel.value = st.bond_level || 1
    bondTitle.value = st.bond_title || '初遇心狐'
    nextLevelAffinity.value = st.next_level_affinity ?? null
    needMoodCheckin.value = Boolean(st.need_mood_checkin)
    todayMoodScore.value = st.today_mood_score || 0
    memories.value = Array.isArray(st.memories) ? st.memories : []
    lastDecayAt = Date.now()
    if (!speaking.value && moodTimer === null) {
      mood.value = st.mood || mapPADToMood(pad.value.valence, pad.value.arousal)
    }
  }

  async function hydrateFromBackend(showReunion = true) {
    try {
      const st = await fetchMascotState()
      applyBackendState(st)
      hydrated.value = true
      if (showReunion && st.reunion_greeting && !drawerOpen.value && !minimized.value) {
        if (st.away_hours >= 48) {
          triggerMoodTemporary('excited', 3800, st.reunion_greeting)
          triggerChoreoAction('sparkle')
        } else {
          showBubble(st.reunion_greeting, 4600)
        }
      }
    } catch {
      // 未登录或离线时静默维持本地 PAD 引擎
    }
  }

  function stepHomeostasisDecay() {
    const now = Date.now()
    const elapsedSec = (now - lastDecayAt) / 1000
    if (elapsedSec < 5) return
    lastDecayAt = now
    pad.value = decayPAD(pad.value, elapsedSec)
    if (moodTimer === null && !speaking.value && mood.value !== 'thinking') {
      mood.value = mapPADToMood(pad.value.valence, pad.value.arousal)
    }
  }

  function setMood(nextMood: MascotMood) {
    clearMoodTimer()
    mood.value = nextMood
  }

  function triggerChoreoAction(act: MascotChoreoAction) {
    if (!act || act === 'none') return
    actionPulse.value = act
    actionSeq.value += 1
  }

  function triggerMoodTemporary(nextMood: MascotMood, durationMs = 2800, bubble?: string) {
    clearMoodTimer()
    mood.value = nextMood
    if (bubble && !drawerOpen.value) {
      showBubble(bubble, Math.max(durationMs + 800, 3200))
    }
    if (durationMs > 0) {
      moodTimer = window.setTimeout(() => {
        moodTimer = null
        stepHomeostasisDecay()
        mood.value = mapPADToMood(pad.value.valence, pad.value.arousal)
      }, durationMs)
    }
  }

  function applyEmoDirective(dir: MascotEmoDirective) {
    pad.value = {
      valence: clamp(pad.value.valence + dir.dv, -1, 1),
      arousal: clamp(pad.value.arousal + dir.da, 0, 1),
      affinity: pad.value.affinity,
    }
    lastDecayAt = Date.now()
    triggerMoodTemporary(dir.emo, 4200)
    triggerChoreoAction(dir.act)
  }

  function pulseSyllableMouth(openness: number) {
    mouthOpenness.value = clamp(openness, 0, 1)
    if (mouthDecayTimer !== null) window.clearTimeout(mouthDecayTimer)
    mouthDecayTimer = window.setTimeout(() => {
      mouthOpenness.value = 0
      mouthDecayTimer = null
    }, 155)
  }

  function showBubble(text: string, durationMs = 4400) {
    if (bubbleTimer !== null) {
      window.clearTimeout(bubbleTimer)
      bubbleTimer = null
    }
    bubbleText.value = text
    if (text && durationMs > 0) {
      bubbleTimer = window.setTimeout(() => {
        if (bubbleText.value === text) {
          scheduler.onBubbleIgnored()
          bubbleText.value = ''
        }
        bubbleTimer = null
      }, durationMs)
    }
  }

  function dismissBubble() {
    scheduler.onBubbleDismissed()
    showBubble('', 0)
  }

  function triggerHappy(text?: string, durationMs = 2600) {
    triggerMoodTemporary('happy', durationMs, text)
    triggerChoreoAction('sparkle')
  }

  function triggerComfort(text?: string, durationMs = 5400) {
    triggerMoodTemporary('comfort', durationMs, text)
    triggerChoreoAction('hug')
  }

  async function dispatchGesture(gesture: MascotGesture) {
    touchActivity()
    scheduler.onUserEngaged()

    // 本地立即零延迟动画反馈
    const localMap: Record<MascotGesture, { mood: MascotMood; act: MascotChoreoAction; dv: number; da: number; bubble: string; dur: number }> = {
      rub_head: { mood: 'happy', act: 'tail_turbo', dv: 0.24, da: 0.14, bubble: '唔~ 摸摸头最舒服啦，耳朵都要化掉咯 ♥', dur: 3200 },
      poke_cheek: { mood: 'shy', act: 'blush', dv: 0.12, da: 0.22, bubble: '呜…别总戳我脸颊嘛，会脸红的啦！', dur: 3000 },
      pull_ear: { mood: 'pout', act: 'ear_twitch', dv: -0.06, da: 0.42, bubble: '呀！狐狸耳朵很敏感的啦，轻一点嘛！', dur: 3000 },
      pull_tail: { mood: 'shy', act: 'ear_twitch', dv: -0.05, da: 0.45, bubble: '哇！尾巴是禁区啦，毛都要炸开咯~', dur: 3000 },
      combo_dizzy: { mood: 'dizzy', act: 'ear_twitch', dv: 0.02, da: 0.52, bubble: '哇哇哇转晕啦 @_@ 眼前全是小星星，停手停手~', dur: 4000 },
      long_hug: { mood: 'comfort', act: 'hug', dv: 0.3, da: -0.24, bubble: '贴贴抱紧你~ 先在这里喘口气吧 💗', dur: 4200 },
      drag_swing: { mood: 'curious', act: 'nod', dv: 0.08, da: 0.28, bubble: '哇飞起来啦~ 这边视野更清楚呢！', dur: 2400 },
      edge_peek: { mood: 'curious', act: 'ear_twitch', dv: 0.06, da: 0.12, bubble: '探头偷看~ 需要我随时点耳朵出来哦！', dur: 2800 },
    }
    const local = localMap[gesture]
    pad.value = {
      valence: clamp(pad.value.valence + local.dv, -1, 1),
      arousal: clamp(pad.value.arousal + local.da, 0, 1),
      affinity: pad.value.affinity,
    }
    triggerMoodTemporary(local.mood, local.dur, local.bubble)
    triggerChoreoAction(local.act)

    try {
      const res = await sendMascotInteract({ gesture })
      if (res?.state) applyBackendState(res.state)
      if (res?.bubble && !drawerOpen.value) {
        showBubble(res.bubble, Math.max(local.dur + 400, 3200))
      }
    } catch {
      // 离线静默降级
    }
  }

  async function recordMoodCheckin(score: number, note = '') {
    touchActivity()
    scheduler.onUserEngaged()
    const res = await submitMascotMoodCheckin({ score, note })
    if (res?.state) applyBackendState(res.state)
    triggerMoodTemporary(res.reaction_mood, 3800)
    if (res.reaction_mood === 'comfort') triggerChoreoAction('hug')
    else triggerChoreoAction('sparkle')
    return res
  }

  async function forgetMemory(memoryId: number) {
    await apiDeleteMascotMemory(memoryId)
    memories.value = memories.value.filter((m) => m.id !== memoryId)
  }

  function tickAutonomous(routePath: string) {
    stepHomeostasisDecay()
    const idleSec = (Date.now() - lastActivityAt) / 1000
    const decision = scheduler.tick({
      idleSec,
      drawerOpen: drawerOpen.value,
      minimized: minimized.value,
      hour: new Date().getHours(),
      pad: pad.value,
      routePath,
    })
    if (!decision) return
    if (decision.choreoAction) triggerChoreoAction(decision.choreoAction)
    if (decision.mood) {
      triggerMoodTemporary(decision.mood, decision.durationMs || 3200, decision.bubble)
    } else if (decision.bubble && !drawerOpen.value) {
      showBubble(decision.bubble, decision.durationMs || 3800)
    }
  }

  /**
   * 感知用户在调试台/输入框中的犹豫或火药味草稿，给出温柔非侵入式主动关怀
   */
  function reportDraftSignal(kind: 'hesitation' | 'heated', draftSample = '') {
    const now = Date.now()
    if (drawerOpen.value || now - lastDraftSignalAt < 45000) return
    lastDraftSignalAt = now
    currentContextHint.value =
      kind === 'heated'
        ? `用户正在起草情绪激动的消息：「${draftSample.slice(0, 80)}」`
        : '用户在输入框反复删改犹豫，似乎拿不准怎么回复'
    if (kind === 'heated') {
      triggerMoodTemporary(
        'comfort',
        4600,
        '先别急着发出去呀~ 点我一下，恋恋帮你降温柔化出 3 个体面版本 🧊',
      )
      triggerChoreoAction('ear_twitch')
    } else {
      triggerMoodTemporary(
        'curious',
        4200,
        '纠结怎么回吗？直接贴给我，帮你拆解潜台词出主意呀 ✨',
      )
      triggerChoreoAction('nod')
    }
  }

  function setPendingToolIntent(intent: MascotToolDirective | null) {
    pendingToolIntent.value = intent
  }

  function consumePendingToolIntent(): MascotToolDirective | null {
    const val = pendingToolIntent.value
    pendingToolIntent.value = null
    return val
  }

  function setSpeaking(next: boolean) {
    speaking.value = next
    if (!next) {
      mouthOpenness.value = 0
    }
  }

  function openDrawer() {
    touchActivity()
    scheduler.onUserEngaged()
    minimized.value = false
    drawerOpen.value = true
    bubbleText.value = ''
    persist()
  }

  function closeDrawer() {
    drawerOpen.value = false
  }

  function toggleDrawer() {
    touchActivity()
    scheduler.onUserEngaged()
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
    touchActivity()
    minimized.value = val
    if (val) {
      drawerOpen.value = false
      bubbleText.value = ''
    }
    persist()
  }

  function setDockPosition(side: MascotDockSide, ratio: number) {
    touchActivity()
    dockSide.value = side
    yRatio.value = clamp(ratio, 0.1, 0.9)
    persist()
  }

  function setSessionId(id: string) {
    sessionId.value = id
  }

  function resetSession() {
    sessionId.value = ''
    mood.value = mapPADToMood(pad.value.valence, pad.value.arousal)
    speaking.value = false
    mouthOpenness.value = 0
  }

  function greetByRoute(routePath: string) {
    if (minimized.value || drawerOpen.value || routePath === lastRouteGreeted) {
      return
    }
    lastRouteGreeted = routePath
    const routeGreetingMap: Record<string, string> = {
      '/ai-playground': '聊天截图也能直接识图分析哦~ 有犹豫的消息摸摸我头随时问！',
      '/knowledge-wiki': '把本地文档编译成 LLM Wiki 并封装成 Skill，对话时点我就能引用哦 ✨',
      '/ai-personas': '这里藏着各种恋爱风格的人格，想怎么调教都可以问我 ✨',
      '/ai-config': '配置好主模型与备用链路后，回复就更稳更聪明啦~',
      '/dashboard': '欢迎回来！摸摸头、戳脸蛋或者长按抱抱，我都会有不同反应哦 ♥',
    }
    const greeting = routeGreetingMap[routePath]
    if (greeting) {
      showBubble(greeting, 4200)
    }
  }

  return {
    pad,
    bondLevel,
    bondTitle,
    nextLevelAffinity,
    needMoodCheckin,
    todayMoodScore,
    memories,
    hydrated,
    mood,
    speaking,
    mouthOpenness,
    actionPulse,
    actionSeq,
    drawerOpen,
    minimized,
    dockSide,
    yRatio,
    sessionId,
    bubbleText,
    pendingToolIntent,
    currentContextHint,
    moodLabel,
    motionParams,
    hydrateFromBackend,
    stepHomeostasisDecay,
    setMood,
    triggerChoreoAction,
    triggerMoodTemporary,
    applyEmoDirective,
    pulseSyllableMouth,
    setSpeaking,
    triggerHappy,
    triggerComfort,
    dispatchGesture,
    recordMoodCheckin,
    forgetMemory,
    tickAutonomous,
    reportDraftSignal,
    setPendingToolIntent,
    consumePendingToolIntent,
    showBubble,
    dismissBubble,
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
