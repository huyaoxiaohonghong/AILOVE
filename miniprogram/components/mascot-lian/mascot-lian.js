const api = require('../../services/api')
const auth = require('../../utils/auth')
const brain = require('../../utils/mascot-brain')

const STORAGE_KEY = 'ailove_mp_mascot_v2'
const AVATAR_PX_W = 70
const AVATAR_PX_H = 78
const EDGE_GAP = 10

const LIAN_SYSTEM_PROMPT = `你是「恋恋」，AILOVE 微信小程序的可爱常驻看板娘（玫瑰心狐娘，头戴心形发卡、有着玫瑰粉狐耳与蓬松白尖狐尾）。
你的性格与回答规范：
1. 温柔细腻、高情商、略带俏皮甜美感，不说油腻套话，绝不说教或指责用户。
2. 回答简洁清晰，尽量控制在 100～180 字以内，善用 1/2/3 短要点，方便手机屏幕一眼看完。
3. 你熟悉小程序全部功能入口，可自然引导并附带工具卡片帮用户一步跳转：
   - 【帮回复/识图】（pages/reply-helper/reply-helper）：支持上传微信聊天截图直接识图分析，或粘贴原话生成 3 条高情商回复。
   - 【先别发·降温】（pages/soften-draft/soften-draft）：冲动生气时先把带刺狠话柔化成体面表达。
   - 【恋爱档案】（pages/love-profile/love-profile）：记录关系阶段、对方性格与沟通雷区。
   - 【话术库】（pages/favorites/favorites）：一键保存并复用好用的高情商金句。
4. 若察觉用户正在难过、焦虑、委屈或处于感情低谷：先真诚抱抱安慰情绪，再给一件此刻能做的小事。请严格遵守系统附带的 [[emo:...]] 动作编排协议。`

const QUICK_ROUTES = [
  { label: '帮回复/识图', path: 'pages/reply-helper/reply-helper' },
  { label: '先别发', path: 'pages/soften-draft/soften-draft' },
  { label: '情感档案', path: 'pages/love-profile/love-profile' },
  { label: '话术库', path: 'pages/favorites/favorites' },
]

const QUICK_PROMPTS = [
  'Ta 已读不回怎么高情商破冰？',
  '好生气想发狠话，先别发帮我降温',
  '聊天截图怎么直接识图分析？',
  '心情有点焦虑，陪我做个呼吸放松',
]

const MOOD_CHOICES = [
  { score: 1, emoji: '🌧️', label: '低落' },
  { score: 2, emoji: '🥺', label: '委屈' },
  { score: 3, emoji: '☁️', label: '平静' },
  { score: 4, emoji: '🌷', label: '不错' },
  { score: 5, emoji: '✨', label: '心动' },
]

const LOCAL_GESTURE_MAP = {
  rub_head: { mood: 'happy', haptic: 'light', symbol: '♥', bubble: '唔~ 摸摸头最舒服啦，耳朵都要化掉咯 ♥', dur: 3200, dv: 0.24, da: 0.14 },
  poke_cheek: { mood: 'shy', haptic: 'light', symbol: '💗', bubble: '呜…别总戳我脸颊嘛，会脸红的啦！', dur: 3000, dv: 0.12, da: 0.22 },
  pull_ear: { mood: 'pout', haptic: 'medium', symbol: '!', bubble: '呀！狐狸耳朵很敏感的啦，轻一点嘛！', dur: 3000, dv: -0.06, da: 0.42 },
  pull_tail: { mood: 'shy', haptic: 'medium', symbol: '💗', bubble: '哇！尾巴是禁区啦，毛都被薅炸开咯~', dur: 3000, dv: -0.05, da: 0.45 },
  combo_dizzy: { mood: 'dizzy', haptic: 'medium', symbol: '⭐', bubble: '哇哇转晕啦 @_@ 眼前全是小星星，停手~', dur: 4000, dv: 0.02, da: 0.52 },
  long_hug: { mood: 'comfort', haptic: 'heartbeat', symbol: '💗', bubble: '贴贴抱紧你~ 先在这里喘口气吧 💗', dur: 4200, dv: 0.3, da: -0.24 },
  drag_swing: { mood: 'curious', haptic: 'light', symbol: '✨', bubble: '哇飞起来啦~ 这边视野更清楚呢！', dur: 2400, dv: 0.08, da: 0.28 },
  edge_peek: { mood: 'curious', haptic: 'light', symbol: '✨', bubble: '探头~ 有拿不准的消息随时点我哦！', dur: 2600, dv: 0.06, da: 0.12 },
}

function getViewportSize() {
  try {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()
    return {
      width: (info && info.windowWidth) || 375,
      height: (info && info.windowHeight) || 667,
    }
  } catch (_e) {
    return { width: 375, height: 667 }
  }
}

Component({
  properties: {
    externalMood: {
      type: String,
      value: '',
      observer() {
        this.syncEffectiveMood()
      },
    },
    bottomOffset: {
      type: Number,
      value: 130,
    },
    pageHint: {
      type: String,
      value: '',
    },
  },

  data: {
    dockSide: 'right',
    leftPx: 295,
    topPx: 460,
    minimized: false,
    dragging: false,
    dragTiltDeg: 0,
    drawerOpen: false,
    bouncing: false,
    effectiveMood: 'idle',
    moodStatusText: '在线陪伴中',
    spritePath: '/assets/mascot/lian-idle.png',
    bubbleText: '',
    burstHearts: [],

    // 恋恋 2.0 情感大脑状态
    bondLevel: 1,
    bondTitle: '初遇心狐',
    affinityPercent: 60,
    needMoodCheckin: false,
    checkingIn: false,
    moodChoices: MOOD_CHOICES,
    memories: [],
    showMemories: false,

    // 4-4-4 呼吸引导圈
    breathingActive: false,
    breathingRemainSec: 30,
    breathingPhase: '吸气 (4s)',
    breathingScale: 1,

    quickRoutes: QUICK_ROUTES,
    quickPrompts: QUICK_PROMPTS,
    messages: [],
    emotionCare: null,
    inputValue: '',
    sending: false,
    sessionId: '',
    scrollIntoId: '',
  },

  lifetimes: {
    attached() {
      const base = brain.getCircadianBaseline()
      this._pad = { valence: base.valence, arousal: base.arousal, affinity: 12 }
      this._localMood = brain.mapPADToMood(base.valence, base.arousal)
      this._blinking = false
      this._heartSeq = 1
      this._streamHandle = null
      this._draftBuffer = null
      this._hintShown = false
      this._scheduler = new brain.UtilityBehaviorScheduler()
      this._lastActivityAt = Date.now()
      this._lastDecayAt = Date.now()
      this._recentTapTimes = []
      this._activeHitZone = 'body'
      this._rubAccumX = 0
      this._rubTriggered = false
      this._longPressFired = false

      this.initPosition()
      this.syncEffectiveMood()
      this.startBlinkLoop()
      this.startAutonomousLoop()
      this.hydrateBackendState(true)
      this.scheduleInitialHint()
    },

    detached() {
      this.abortActiveStream()
      this.stopBreathing()
      this.clearAllTimers()
    },
  },

  pageLifetimes: {
    show() {
      this.initPosition()
      this.startBlinkLoop()
      this.startAutonomousLoop()
      this.hydrateBackendState(false)
    },
    hide() {
      this.clearBlinkTimers()
      this.clearAutonomousTimer()
      this.stopBreathing()
    },
  },

  methods: {
    noop() {},

    touchActivity() {
      this._lastActivityAt = Date.now()
    },

    clearBlinkTimers() {
      if (this._blinkTimer) { clearTimeout(this._blinkTimer); this._blinkTimer = null }
      if (this._blinkEndTimer) { clearTimeout(this._blinkEndTimer); this._blinkEndTimer = null }
      if (this._doubleBlinkTimer) { clearTimeout(this._doubleBlinkTimer); this._doubleBlinkTimer = null }
    },

    clearAutonomousTimer() {
      if (this._autoTimer) {
        clearInterval(this._autoTimer)
        this._autoTimer = null
      }
    },

    clearLongPress() {
      if (this._longPressTimer) {
        clearTimeout(this._longPressTimer)
        this._longPressTimer = null
      }
    },

    clearAllTimers() {
      this.clearBlinkTimers()
      this.clearAutonomousTimer()
      this.clearLongPress()
      if (this._moodTimer) { clearTimeout(this._moodTimer); this._moodTimer = null }
      if (this._bubbleTimer) { clearTimeout(this._bubbleTimer); this._bubbleTimer = null }
      if (this._bounceTimer) { clearTimeout(this._bounceTimer); this._bounceTimer = null }
      if (this._flushTimer) { clearTimeout(this._flushTimer); this._flushTimer = null }
      if (this._hintTimer) { clearTimeout(this._hintTimer); this._hintTimer = null }
      if (this._heartsTimer) { clearTimeout(this._heartsTimer); this._heartsTimer = null }
    },

    initPosition() {
      const vp = getViewportSize()
      this._vpWidth = vp.width
      this._vpHeight = vp.height

      const rpxBottom = Number(this.data.bottomOffset) || 130
      const bottomPx = (rpxBottom * vp.width) / 750
      const defaultTop = Math.max(76, Math.min(vp.height - AVATAR_PX_H - 24, vp.height - AVATAR_PX_H - bottomPx))

      let dockSide = 'right'
      let topPx = defaultTop
      let minimized = false

      try {
        const saved = wx.getStorageSync(STORAGE_KEY) || wx.getStorageSync('ailove_mp_mascot_v1')
        if (saved && typeof saved === 'object') {
          dockSide = saved.dockSide === 'left' ? 'left' : 'right'
          if (typeof saved.topPx === 'number' && Number.isFinite(saved.topPx)) {
            topPx = Math.max(76, Math.min(vp.height - AVATAR_PX_H - 24, saved.topPx))
          }
          minimized = Boolean(saved.minimized)
        }
      } catch (_e) {}

      const leftPx = dockSide === 'left' ? EDGE_GAP : Math.max(EDGE_GAP, vp.width - AVATAR_PX_W - EDGE_GAP)
      this.setData({
        dockSide,
        leftPx: Math.round(leftPx),
        topPx: Math.round(topPx),
        minimized,
      })
    },

    persistPosition(nextState) {
      try {
        wx.setStorageSync(STORAGE_KEY, {
          dockSide: nextState.dockSide || this.data.dockSide,
          topPx: typeof nextState.topPx === 'number' ? nextState.topPx : this.data.topPx,
          minimized: typeof nextState.minimized === 'boolean' ? nextState.minimized : this.data.minimized,
        })
      } catch (_e) {}
    },

    applyBackendState(st) {
      if (!st || typeof st !== 'object') return
      this._pad = {
        valence: brain.clamp(Number(st.valence != null ? st.valence : 0.25), -1, 1),
        arousal: brain.clamp(Number(st.arousal != null ? st.arousal : 0.35), 0, 1),
        affinity: brain.clamp(Number(st.affinity != null ? st.affinity : 12), 0, 100),
      }
      this._lastDecayAt = Date.now()
      const nextTarget = st.next_level_affinity || 100
      const pct = Math.round(brain.clamp((this._pad.affinity / nextTarget) * 100, 6, 100))
      if (!this._moodTimer && !this.data.sending && st.mood) {
        this._localMood = st.mood
      }
      this.setData({
        bondLevel: st.bond_level || 1,
        bondTitle: st.bond_title || '初遇心狐',
        affinityPercent: pct,
        needMoodCheckin: Boolean(st.need_mood_checkin),
        memories: Array.isArray(st.memories) ? st.memories : [],
      })
      this.syncEffectiveMood()
    },

    async hydrateBackendState(showReunion) {
      if (!auth.getToken()) return
      try {
        const st = await api.getMascotState()
        this.applyBackendState(st)
        if (showReunion && st && st.reunion_greeting && !this.data.minimized && !this.data.drawerOpen) {
          this._hintShown = true
          if (st.away_hours >= 48) {
            this.setLocalMood('excited', 3800)
          }
          this.showBubble(st.reunion_greeting, 4200)
        }
      } catch (_e) {
        // 离线静默降级
      }
    },

    syncEffectiveMood() {
      const ext = (this.data.externalMood || '').trim()
      const active = ext || this._localMood || 'idle'
      const allowBlink = active === 'idle' || active === 'comfort' || active === 'shy' || active === 'curious'
      const spriteKey = allowBlink && this._blinking ? 'blink' : (brain.MOOD_SPRITE_MAP[active] || 'idle')
      this.setData({
        effectiveMood: active,
        moodStatusText: brain.MOOD_LABELS[active] || '在线陪伴中',
        spritePath: `/assets/mascot/lian-${spriteKey}.png`,
      })
    },

    setLocalMood(mood, resetMs) {
      if (this._moodTimer) {
        clearTimeout(this._moodTimer)
        this._moodTimer = null
      }
      this._localMood = mood
      this.syncEffectiveMood()
      if (resetMs > 0) {
        this._moodTimer = setTimeout(() => {
          this._moodTimer = null
          this.stepHomeostasisDecay()
          this._localMood = brain.mapPADToMood(this._pad.valence, this._pad.arousal)
          this.syncEffectiveMood()
        }, resetMs)
      }
    },

    stepHomeostasisDecay() {
      const now = Date.now()
      const dt = (now - (this._lastDecayAt || now)) / 1000
      if (dt < 5) return
      this._lastDecayAt = now
      this._pad = brain.decayPAD(this._pad, dt)
    },

    startBlinkLoop() {
      this.clearBlinkTimers()
      const sample = brain.sampleWeibullBlinkDelayMs(this._localMood === 'sleepy')
      this._blinkTimer = setTimeout(() => {
        this._blinking = true
        this.syncEffectiveMood()
        this._blinkEndTimer = setTimeout(() => {
          this._blinking = false
          this.syncEffectiveMood()
          if (sample.doubleBlink) {
            this._doubleBlinkTimer = setTimeout(() => {
              this._blinking = true
              this.syncEffectiveMood()
              this._blinkEndTimer = setTimeout(() => {
                this._blinking = false
                this.syncEffectiveMood()
                this.startBlinkLoop()
              }, 115)
            }, 140)
          } else {
            this.startBlinkLoop()
          }
        }, 135)
      }, sample.delayMs)
    },

    startAutonomousLoop() {
      this.clearAutonomousTimer()
      this._autoTimer = setInterval(() => {
        this.stepHomeostasisDecay()
        const idleSec = (Date.now() - (this._lastActivityAt || Date.now())) / 1000
        const decision = this._scheduler.tick({
          idleSec,
          drawerOpen: this.data.drawerOpen,
          minimized: this.data.minimized,
          hour: new Date().getHours(),
        })
        if (!decision) return
        if (decision.mood) {
          this.setLocalMood(decision.mood, decision.durationMs || 3000)
        }
        if (decision.bubble && !this.data.drawerOpen) {
          this.showBubble(decision.bubble, decision.durationMs || 3800)
        }
      }, 10000)
    },

    scheduleInitialHint() {
      const hint = (this.data.pageHint || '').trim()
      if (!hint || this._hintShown || this.data.minimized || this.data.drawerOpen) return
      this._hintTimer = setTimeout(() => {
        if (this._hintShown || this.data.minimized || this.data.drawerOpen) return
        this._hintShown = true
        this.showBubble(hint, 4000)
      }, 950)
    },

    showBubble(text, durationMs) {
      if (this._bubbleTimer) {
        clearTimeout(this._bubbleTimer)
        this._bubbleTimer = null
      }
      this.setData({ bubbleText: text || '' })
      if (text && durationMs > 0) {
        this._bubbleTimer = setTimeout(() => {
          this.setData({ bubbleText: '' })
          this._bubbleTimer = null
        }, durationMs)
      }
    },

    onCloseBubble() {
      if (this._scheduler) this._scheduler.onBubbleDismissed()
      this.showBubble('', 0)
    },

    triggerTapFeedback(symbol) {
      const sym = symbol || '♥'
      this.setData({ bouncing: true })
      if (this._bounceTimer) clearTimeout(this._bounceTimer)
      this._bounceTimer = setTimeout(() => {
        this.setData({ bouncing: false })
        this._bounceTimer = null
      }, 520)

      const hearts = [
        { id: this._heartSeq++, sym, tx: -26, ty: -52 },
        { id: this._heartSeq++, sym, tx: 2, ty: -66 },
        { id: this._heartSeq++, sym, tx: 28, ty: -48 },
      ]
      this.setData({ burstHearts: hearts })
      if (this._heartsTimer) clearTimeout(this._heartsTimer)
      this._heartsTimer = setTimeout(() => {
        this.setData({ burstHearts: [] })
        this._heartsTimer = null
      }, 860)
    },

    async dispatchGesture(gesture) {
      this.touchActivity()
      if (this._scheduler) this._scheduler.onUserEngaged()
      const spec = LOCAL_GESTURE_MAP[gesture] || LOCAL_GESTURE_MAP.rub_head
      this._pad = {
        valence: brain.clamp(this._pad.valence + spec.dv, -1, 1),
        arousal: brain.clamp(this._pad.arousal + spec.da, 0, 1),
        affinity: this._pad.affinity,
      }
      brain.triggerHaptic(spec.haptic)
      this.triggerTapFeedback(spec.symbol)
      this.setLocalMood(spec.mood, spec.dur)
      if (!this.data.drawerOpen) {
        this.showBubble(spec.bubble, spec.dur + 400)
      }
      if (!auth.getToken()) return
      try {
        const res = await api.sendMascotInteract({ gesture })
        if (res && res.state) this.applyBackendState(res.state)
        if (res && res.bubble && !this.data.drawerOpen) {
          this.showBubble(res.bubble, spec.dur + 400)
        }
      } catch (_e) {
        // 离线静默降级
      }
    },

    onTouchStart(e) {
      const touch = e.touches && e.touches[0]
      if (!touch) return
      const vp = getViewportSize()
      this._vpWidth = vp.width
      this._vpHeight = vp.height
      this._touchStartX = touch.clientX
      this._touchStartY = touch.clientY
      this._prevClientX = touch.clientX
      this._startLeft = this.data.leftPx
      this._startTop = this.data.topPx
      this._hasMoved = false
      this._rubAccumX = 0
      this._rubTriggered = false
      this._longPressFired = false

      const relX = (touch.clientX - this.data.leftPx) / AVATAR_PX_W
      const relY = (touch.clientY - this.data.topPx) / AVATAR_PX_H
      this._activeHitZone = brain.classifyHitZone(relX, relY)

      this.clearLongPress()
      this._longPressTimer = setTimeout(() => {
        if (!this._hasMoved && !this._rubTriggered) {
          this._longPressFired = true
          this.dispatchGesture('long_hug')
        }
      }, 560)
    },

    onTouchMove(e) {
      const touch = e.touches && e.touches[0]
      if (!touch) return
      const dx = touch.clientX - this._touchStartX
      const dy = touch.clientY - this._touchStartY
      const stepDx = touch.clientX - (this._prevClientX || touch.clientX)
      this._prevClientX = touch.clientX

      // 头顶/耳朵横向轻搓 -> 触发「摸头杀」，不进入拖拽位移
      if (
        !this._hasMoved &&
        (this._activeHitZone === 'head' || this._activeHitZone === 'ear') &&
        Math.abs(dy) < 24
      ) {
        this._rubAccumX += Math.abs(stepDx)
        if (this._rubAccumX >= 36 && !this._rubTriggered) {
          this._rubTriggered = true
          this.clearLongPress()
          this.dispatchGesture('rub_head')
        }
        if (this._rubAccumX >= 12) return
      }

      if (!this._hasMoved && Math.hypot(dx, dy) > 9) {
        this._hasMoved = true
        this.clearLongPress()
        this.setData({ dragging: true })
      }
      if (this._hasMoved) {
        const vpW = this._vpWidth || 375
        const vpH = this._vpHeight || 667
        const nextLeft = Math.max(6, Math.min(vpW - AVATAR_PX_W - 6, this._startLeft + dx))
        const nextTop = Math.max(76, Math.min(vpH - AVATAR_PX_H - 20, this._startTop + dy))
        const tilt = Math.round(brain.clamp(-stepDx * 1.4, -22, 22))
        this.setData({
          leftPx: Math.round(nextLeft),
          topPx: Math.round(nextTop),
          dragTiltDeg: tilt,
        })
      }
    },

    onTouchEnd() {
      this.clearLongPress()
      if (this._longPressFired || this._rubTriggered) {
        this._longPressFired = false
        this._rubTriggered = false
        return
      }
      if (this._hasMoved) {
        const vpW = this._vpWidth || 375
        const dockSide = this.data.leftPx + AVATAR_PX_W / 2 < vpW / 2 ? 'left' : 'right'
        const snapLeft = dockSide === 'left' ? EDGE_GAP : Math.max(EDGE_GAP, vpW - AVATAR_PX_W - EDGE_GAP)
        this.setData({
          dragging: false,
          dragTiltDeg: 0,
          dockSide,
          leftPx: Math.round(snapLeft),
        })
        this.persistPosition({ dockSide, topPx: this.data.topPx })
        this._hasMoved = false
        this.dispatchGesture('drag_swing')
        return
      }
      this.onTapMascot()
    },

    onTapMascot() {
      this.touchActivity()
      const now = Date.now()
      this._recentTapTimes = (this._recentTapTimes || []).filter((t) => now - t < 2000)
      this._recentTapTimes.push(now)

      // 2 秒连戳 5 次 -> 晕眩彩蛋 @_@
      if (this._recentTapTimes.length >= 5) {
        this._recentTapTimes = []
        this.dispatchGesture('combo_dizzy')
        return
      }

      if (!this.data.drawerOpen && this._activeHitZone === 'ear') {
        this.dispatchGesture('pull_ear')
        return
      }
      if (!this.data.drawerOpen && this._activeHitZone === 'tail') {
        this.dispatchGesture('pull_tail')
        return
      }
      if (!this.data.drawerOpen && this._activeHitZone === 'cheek') {
        this.dispatchGesture('poke_cheek')
        return
      }

      brain.triggerHaptic('light')
      this.triggerTapFeedback('♥')
      const nextOpen = !this.data.drawerOpen
      this.setData({
        drawerOpen: nextOpen,
        bubbleText: nextOpen ? '' : this.data.bubbleText,
      })
      if (nextOpen) {
        this.hydrateBackendState(false)
      }
    },

    onOpenFromBubble() {
      brain.triggerHaptic('light')
      this.triggerTapFeedback('♥')
      this.setData({
        drawerOpen: true,
        bubbleText: '',
      })
      this.hydrateBackendState(false)
    },

    onMinimize() {
      this.setData({
        minimized: true,
        drawerOpen: false,
        bubbleText: '',
      })
      this.persistPosition({ minimized: true })
    },

    onRestore() {
      this.setData({ minimized: false })
      this.persistPosition({ minimized: false })
      this.dispatchGesture('edge_peek')
    },

    onCloseDrawer() {
      this.stopBreathing()
      this.setData({ drawerOpen: false, showMemories: false })
    },

    onToggleMemories() {
      this.setData({ showMemories: !this.data.showMemories })
    },

    async onForgetMemory(e) {
      const id = Number(e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.id)
      if (!id) return
      try {
        await api.deleteMascotMemory(id)
        const next = (this.data.memories || []).filter((m) => m.id !== id)
        this.setData({ memories: next })
        wx.showToast({ title: '已帮恋恋忘掉这条记忆', icon: 'none' })
      } catch (_e) {
        wx.showToast({ title: '删除失败', icon: 'none' })
      }
    },

    async onTapMoodCheckin(e) {
      const score = Number(e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.score)
      if (!score || this.data.checkingIn) return
      this.setData({ checkingIn: true })
      try {
        await auth.ensureLogin()
        const res = await api.submitMascotMoodCheckin({ score })
        if (res && res.state) this.applyBackendState(res.state)
        brain.triggerHaptic(score <= 2 ? 'heartbeat' : 'light')
        this.setLocalMood(res.reaction_mood || 'happy', 3800)
        const msg = {
          id: `ci_${Date.now()}`,
          role: 'assistant',
          content: `【今日心情：${res.label}】\n${res.reply}`,
          favorited: false,
          toolCard:
            score <= 2
              ? { type: 'start_calm_breathing', label: '跟恋恋做 30 秒呼吸放松', seconds: 30 }
              : null,
          toolApplied: false,
        }
        this.setData({
          messages: this.data.messages.concat([msg]),
          scrollIntoId: 'lian-bottom-anchor',
        })
      } catch (err) {
        wx.showToast({ title: (err && err.message) || '打卡失败', icon: 'none' })
      } finally {
        this.setData({ checkingIn: false })
      }
    },

    stopBreathing() {
      if (this._breathingTimer) {
        clearInterval(this._breathingTimer)
        this._breathingTimer = null
      }
      if (this.data.breathingActive) {
        this.setData({ breathingActive: false, breathingScale: 1 })
      }
    },

    startCalmBreathing(seconds) {
      this.stopBreathing()
      const total = Math.max(12, Math.min(60, Number(seconds) || 30))
      this.setLocalMood('comfort', 0)
      let elapsed = 0
      const updateCycle = (remain) => {
        const c = elapsed % 12
        let phase = '吸气 (4s)'
        let scale = 1.22
        if (c >= 4 && c < 8) {
          phase = '屏息 (4s)'
          scale = 1.22
        } else if (c >= 8) {
          phase = '慢呼气 (4s)'
          scale = 0.88
        }
        this.setData({
          breathingActive: true,
          breathingRemainSec: remain,
          breathingPhase: phase,
          breathingScale: scale,
        })
      }
      updateCycle(total)
      let remain = total
      this._breathingTimer = setInterval(() => {
        elapsed += 1
        remain -= 1
        if (remain <= 0) {
          this.stopBreathing()
          brain.triggerHaptic('light')
          this.setLocalMood('happy', 3000)
          wx.showToast({ title: '呼吸引导完成，轻松一点了吗 💗', icon: 'none' })
          return
        }
        updateCycle(remain)
      }, 1000)
    },

    async onTapToolCard(e) {
      const idx = Number(e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.idx)
      const msg = this.data.messages[idx]
      const tool = msg && msg.toolCard
      if (!tool) return

      if (tool.type === 'start_calm_breathing') {
        this.startCalmBreathing(tool.seconds || 30)
        return
      }
      if (tool.type === 'propose_profile_update' && tool.patch) {
        if (msg.toolApplied) return
        try {
          await auth.ensureLogin()
          await api.applyMascotProfilePatch(tool.patch)
          this.setData({ [`messages[${idx}].toolApplied`]: true })
          brain.triggerHaptic('light')
          this.setLocalMood('happy', 2600)
          wx.showToast({ title: '已顺手记入情感档案', icon: 'success' })
        } catch (err) {
          wx.showToast({ title: (err && err.message) || '同步失败', icon: 'none' })
        }
        return
      }

      const app = getApp()
      if (app && typeof app.setToolIntent === 'function') {
        app.setToolIntent(tool)
      }
      this.setData({ drawerOpen: false })
      if (tool.type === 'open_reply_helper') {
        wx.navigateTo({ url: '/pages/reply-helper/reply-helper' })
      } else if (tool.type === 'open_soften_draft') {
        wx.navigateTo({ url: '/pages/soften-draft/soften-draft' })
      }
    },

    onResetTopic() {
      this.abortActiveStream()
      this.stopBreathing()
      this.setData({
        messages: [],
        emotionCare: null,
        sending: false,
        sessionId: '',
      })
      this.setLocalMood('idle', 0)
    },

    onInputChange(e) {
      this.setData({ inputValue: (e.detail && e.detail.value) || '' })
    },

    onQuickNav(e) {
      const targetPath = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.path) || ''
      if (!targetPath) return
      const pages = getCurrentPages()
      const cur = pages && pages[pages.length - 1]
      const curRoute = cur && cur.route
      this.setData({ drawerOpen: false })
      if (curRoute === targetPath) {
        wx.showToast({ title: '已经在这一页啦~', icon: 'none' })
        return
      }
      wx.navigateTo({ url: `/${targetPath}` })
    },

    onQuickPrompt(e) {
      const q = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.prompt) || ''
      if (q) this.sendPrompt(q)
    },

    onSendInput() {
      this.sendPrompt(this.data.inputValue)
    },

    abortActiveStream() {
      if (this._streamHandle && typeof this._streamHandle.abort === 'function') {
        try {
          this._streamHandle.abort()
        } catch (_e) {}
      }
      this._streamHandle = null
      this._draftBuffer = null
      if (this._flushTimer) {
        clearTimeout(this._flushTimer)
        this._flushTimer = null
      }
    },

    scheduleFlush(aiIdx) {
      if (this._flushTimer) return
      this._flushTimer = setTimeout(() => {
        this._flushTimer = null
        this.flushNow(aiIdx)
      }, 65)
    },

    flushNow(aiIdx) {
      if (this._flushTimer) {
        clearTimeout(this._flushTimer)
        this._flushTimer = null
      }
      if (!this._draftBuffer) return
      const snapshot = Object.assign({}, this._draftBuffer)
      this.setData({
        [`messages[${aiIdx}]`]: snapshot,
        scrollIntoId: 'lian-bottom-anchor',
      })
    },

    async sendPrompt(rawText) {
      const text = (rawText || '').trim()
      if (!text || this.data.sending) return

      this.touchActivity()
      this.setData({ inputValue: '' })

      const userMsg = { id: `u_${Date.now()}`, role: 'user', content: text }
      const aiMsg = {
        id: `a_${Date.now() + 1}`,
        role: 'assistant',
        content: '',
        favorited: false,
        toolCard: null,
        toolApplied: false,
      }

      const nextMessages = this.data.messages.concat([userMsg, aiMsg])
      const aiIdx = nextMessages.length - 1
      this._draftBuffer = Object.assign({}, aiMsg)

      this.setData({
        messages: nextMessages,
        emotionCare: null,
        sending: true,
        scrollIntoId: 'lian-bottom-anchor',
      })
      this.setLocalMood('thinking', 0)

      let receivedCare = false
      let receivedEmo = false
      const parser = new brain.StreamingChoreographyParser({
        onEmo: (dir) => {
          receivedEmo = true
          this._pad = {
            valence: brain.clamp(this._pad.valence + dir.dv, -1, 1),
            arousal: brain.clamp(this._pad.arousal + dir.da, 0, 1),
            affinity: this._pad.affinity,
          }
          if (!receivedCare) {
            this.setLocalMood(dir.emo, 4200)
          }
        },
        onTool: (tool) => {
          if (this._draftBuffer) {
            this._draftBuffer.toolCard = tool
            this.scheduleFlush(aiIdx)
          }
        },
        onText: (cleanChunk) => {
          if (!receivedCare && !receivedEmo && this._localMood === 'thinking') {
            this.setLocalMood('idle', 0)
          }
          if (this._draftBuffer) {
            this._draftBuffer.content += cleanChunk
            this.scheduleFlush(aiIdx)
          }
        },
      })

      try {
        await auth.ensureLogin()
        const ephemeralHistory = this.data.messages
          .slice(0, -2)
          .slice(-6)
          .filter((item) => item && item.content)
          .map((item) => ({ role: item.role, content: item.content }))

        const handle = api.streamAiChat(
          {
            message: text,
            session_id: this.data.sessionId || undefined,
            system_prompt: LIAN_SYSTEM_PROMPT,
            temperature: 0.75,
            timezone: 'Asia/Shanghai',
            use_love_profile: true,
            mascot_mode: true,
            mascot_context: '微信小程序首页恋恋问答舱',
            ephemeral_history: ephemeralHistory,
          },
          {
            onMeta: (meta) => {
              if (meta && meta.session_id) {
                this.setData({ sessionId: meta.session_id })
              }
              if (meta && meta.emotion_care) {
                receivedCare = true
                this.setData({ emotionCare: meta.emotion_care })
                this.setLocalMood('comfort', 5400)
              }
            },
            onDelta: (chunk) => {
              parser.feed(chunk)
            },
            onError: (errMsg) => {
              parser.flush()
              if (this._draftBuffer && !this._draftBuffer.content) {
                this._draftBuffer.content = `哎呀，恋恋信号晃了一下：${errMsg || '再试一次吧~'}`
              }
              this.flushNow(aiIdx)
              this.setLocalMood('comfort', 3000)
            },
          },
        )
        this._streamHandle = handle
        await handle.promise
        parser.flush()
        this.flushNow(aiIdx)
        if (!receivedCare && !receivedEmo && this._draftBuffer && this._draftBuffer.content) {
          this.setLocalMood('happy', 2400)
        }
        this.hydrateBackendState(false)
      } catch (err) {
        parser.flush()
        if (this._draftBuffer && !this._draftBuffer.content) {
          this._draftBuffer.content = `抱歉呀，刚刚网络开小差了：${(err && err.message) || '请稍后重试~'}`
          this.flushNow(aiIdx)
        }
        this.setLocalMood('comfort', 3000)
      } finally {
        this._streamHandle = null
        this._draftBuffer = null
        this.setData({ sending: false })
      }
    },

    onCopyReply(e) {
      const content = (e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.content) || ''
      if (!content) return
      wx.setClipboardData({
        data: content,
        success() {
          wx.showToast({ title: '已复制给力话术', icon: 'success' })
        },
      })
    },

    async onFavoriteReply(e) {
      const idx = Number(e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.idx)
      const msg = this.data.messages[idx]
      if (!msg || !msg.content || msg.favorited) return
      try {
        await auth.ensureLogin()
        await api.saveFavorite({
          content: msg.content.slice(0, 1200),
          category: 'chat',
          scene_label: '恋恋小课堂',
          note: '来自小程序看板娘恋恋',
        })
        this.setData({ [`messages[${idx}].favorited`]: true })
        brain.triggerHaptic('light')
        this.setLocalMood('happy', 2200)
        wx.showToast({ title: '已存入话术库', icon: 'success' })
      } catch (err) {
        wx.showToast({ title: (err && err.message) || '收藏失败', icon: 'none' })
      }
    },

    onGoFullChat() {
      const app = getApp()
      if (app && typeof app.setChatIntent === 'function') {
        app.setChatIntent(this.data.sessionId ? { sessionId: this.data.sessionId } : { newChat: true })
      }
      this.setData({ drawerOpen: false })
      wx.switchTab({ url: '/pages/chat/chat' })
    },
  },
})
