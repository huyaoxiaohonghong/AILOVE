const api = require('../../services/api')
const auth = require('../../utils/auth')

const STORAGE_KEY = 'ailove_mp_mascot_v1'
const AVATAR_PX_W = 84
const AVATAR_PX_H = 92
const EDGE_GAP = 10

const LIAN_SYSTEM_PROMPT = `你是「恋恋」，AILOVE 微信小程序的可爱常驻看板娘（玫瑰心狐娘，头戴心形发卡、有着玫瑰粉狐耳与蓬松白尖狐尾）。
你的性格与回答规范：
1. 温柔细腻、高情商、略带俏皮甜美感，不说油腻套话，绝不说教或指责用户。
2. 回答简洁清晰，尽量控制在 100～200 字以内，善用 1/2/3 短要点，方便手机屏幕一眼看完。
3. 你熟悉小程序全部功能入口，可自然引导用户去使用：
   - 【帮回复/识图】（pages/reply-helper/reply-helper）：可上传最多 3 张聊天截图直接识图分析，或粘贴原话生成 3 条高情商回复。
   - 【先别发·降温】（pages/soften-draft/soften-draft）：冲动或生气想发长文时先柔化语气，避免伤感情。
   - 【恋爱画像】（pages/love-profile/love-profile）：填写关系阶段、对方性格和沟通雷区，AI 会自动记住并越聊越懂你们。
   - 【话术收藏】（pages/favorites/favorites）：一键保存并复用好用的开场白和高情商金句。
4. 若察觉用户正在难过、焦虑、委屈或处于感情低谷：先真诚抱抱安慰情绪，再给一件此刻能做的小事。`

const QUICK_ROUTES = [
  { label: '帮回复/识图', path: 'pages/reply-helper/reply-helper' },
  { label: '先别发', path: 'pages/soften-draft/soften-draft' },
  { label: '恋爱画像', path: 'pages/love-profile/love-profile' },
  { label: '话术库', path: 'pages/favorites/favorites' },
]

const QUICK_PROMPTS = [
  '聊天截图怎么直接识图？',
  'Ta 已读不回怎么高情商破冰？',
  '好生气，先别发怎么帮我降温？',
  '恋爱画像填哪些内容最管用？',
]

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
      value: 140,
    },
    pageHint: {
      type: String,
      value: '',
    },
  },

  data: {
    dockSide: 'right',
    leftPx: 281,
    topPx: 460,
    minimized: false,
    dragging: false,
    drawerOpen: false,
    bouncing: false,
    effectiveMood: 'idle',
    moodStatusText: '在线陪伴中',
    spritePath: '/assets/mascot/lian-idle.png',
    bubbleText: '',
    burstHearts: [],

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
      this._localMood = 'idle'
      this._blinking = false
      this._heartSeq = 1
      this._streamHandle = null
      this._draftBuffer = null
      this._hintShown = false

      this.initPosition()
      this.syncEffectiveMood()
      this.startBlinkLoop()
      this.scheduleInitialHint()
    },

    detached() {
      this.abortActiveStream()
      this.clearAllTimers()
    },
  },

  pageLifetimes: {
    show() {
      this.initPosition()
      this.startBlinkLoop()
    },
    hide() {
      this.clearBlinkTimers()
    },
  },

  methods: {
    noop() {},

    clearBlinkTimers() {
      if (this._blinkTimer) {
        clearTimeout(this._blinkTimer)
        this._blinkTimer = null
      }
      if (this._blinkEndTimer) {
        clearTimeout(this._blinkEndTimer)
        this._blinkEndTimer = null
      }
    },

    clearAllTimers() {
      this.clearBlinkTimers()
      if (this._moodTimer) {
        clearTimeout(this._moodTimer)
        this._moodTimer = null
      }
      if (this._bubbleTimer) {
        clearTimeout(this._bubbleTimer)
        this._bubbleTimer = null
      }
      if (this._bounceTimer) {
        clearTimeout(this._bounceTimer)
        this._bounceTimer = null
      }
      if (this._flushTimer) {
        clearTimeout(this._flushTimer)
        this._flushTimer = null
      }
      if (this._hintTimer) {
        clearTimeout(this._hintTimer)
        this._hintTimer = null
      }
      if (this._heartsTimer) {
        clearTimeout(this._heartsTimer)
        this._heartsTimer = null
      }
    },

    initPosition() {
      const vp = getViewportSize()
      this._vpWidth = vp.width
      this._vpHeight = vp.height

      const rpxBottom = Number(this.data.bottomOffset) || 140
      const bottomPx = (rpxBottom * vp.width) / 750
      const defaultTop = Math.max(76, Math.min(vp.height - AVATAR_PX_H - 24, vp.height - AVATAR_PX_H - bottomPx))

      let dockSide = 'right'
      let topPx = defaultTop
      let minimized = false

      try {
        const saved = wx.getStorageSync(STORAGE_KEY)
        if (saved && typeof saved === 'object') {
          dockSide = saved.dockSide === 'left' ? 'left' : 'right'
          if (typeof saved.topPx === 'number' && Number.isFinite(saved.topPx)) {
            topPx = Math.max(76, Math.min(vp.height - AVATAR_PX_H - 24, saved.topPx))
          }
          minimized = Boolean(saved.minimized)
        }
      } catch (_e) {
        // ignore storage errors
      }

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
        const payload = {
          dockSide: nextState.dockSide || this.data.dockSide,
          topPx: typeof nextState.topPx === 'number' ? nextState.topPx : this.data.topPx,
          minimized: typeof nextState.minimized === 'boolean' ? nextState.minimized : this.data.minimized,
        }
        wx.setStorageSync(STORAGE_KEY, payload)
      } catch (_e) {
        // ignore storage errors
      }
    },

    syncEffectiveMood() {
      const ext = (this.data.externalMood || '').trim()
      const active = ext || this._localMood || 'idle'
      const useBlink = (active === 'idle' || active === 'comfort') && this._blinking
      const spriteName = useBlink ? 'blink' : active
      const statusMap = {
        thinking: '歪头思考中...',
        happy: '开心转圈圈 ✨',
        comfort: '递热可可抱抱',
        idle: '在线陪伴中',
      }
      this.setData({
        effectiveMood: active,
        moodStatusText: statusMap[active] || '在线陪伴中',
        spritePath: `/assets/mascot/lian-${spriteName}.png`,
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
          this._localMood = 'idle'
          this.syncEffectiveMood()
          this._moodTimer = null
        }, resetMs)
      }
    },

    startBlinkLoop() {
      this.clearBlinkTimers()
      const delay = 2900 + Math.random() * 1700
      this._blinkTimer = setTimeout(() => {
        this._blinking = true
        this.syncEffectiveMood()
        this._blinkEndTimer = setTimeout(() => {
          this._blinking = false
          this.syncEffectiveMood()
          this.startBlinkLoop()
        }, 140)
      }, delay)
    },

    scheduleInitialHint() {
      const hint = (this.data.pageHint || '').trim()
      if (!hint || this._hintShown || this.data.minimized || this.data.drawerOpen) return
      this._hintTimer = setTimeout(() => {
        this._hintShown = true
        if (!this.data.minimized && !this.data.drawerOpen) {
          this.showBubble(hint, 4200)
        }
      }, 750)
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
      this.showBubble('', 0)
    },

    triggerTapFeedback() {
      this.setData({ bouncing: true })
      if (this._bounceTimer) clearTimeout(this._bounceTimer)
      this._bounceTimer = setTimeout(() => {
        this.setData({ bouncing: false })
        this._bounceTimer = null
      }, 540)

      const hearts = [
        { id: this._heartSeq++, tx: -26, ty: -54 },
        { id: this._heartSeq++, tx: 2, ty: -68 },
        { id: this._heartSeq++, tx: 28, ty: -50 },
      ]
      this.setData({ burstHearts: hearts })
      if (this._heartsTimer) clearTimeout(this._heartsTimer)
      this._heartsTimer = setTimeout(() => {
        this.setData({ burstHearts: [] })
        this._heartsTimer = null
      }, 860)
    },

    onTouchStart(e) {
      const touch = e.touches && e.touches[0]
      if (!touch) return
      const vp = getViewportSize()
      this._vpWidth = vp.width
      this._vpHeight = vp.height
      this._touchStartX = touch.clientX
      this._touchStartY = touch.clientY
      this._startLeft = this.data.leftPx
      this._startTop = this.data.topPx
      this._hasMoved = false
    },

    onTouchMove(e) {
      const touch = e.touches && e.touches[0]
      if (!touch) return
      const dx = touch.clientX - this._touchStartX
      const dy = touch.clientY - this._touchStartY
      if (!this._hasMoved && Math.hypot(dx, dy) > 8) {
        this._hasMoved = true
        this.setData({ dragging: true })
      }
      if (this._hasMoved) {
        const vpW = this._vpWidth || 375
        const vpH = this._vpHeight || 667
        const nextLeft = Math.max(6, Math.min(vpW - AVATAR_PX_W - 6, this._startLeft + dx))
        const nextTop = Math.max(76, Math.min(vpH - AVATAR_PX_H - 20, this._startTop + dy))
        this.setData({
          leftPx: Math.round(nextLeft),
          topPx: Math.round(nextTop),
        })
      }
    },

    onTouchEnd() {
      if (this._hasMoved) {
        const vpW = this._vpWidth || 375
        const dockSide = this.data.leftPx + AVATAR_PX_W / 2 < vpW / 2 ? 'left' : 'right'
        const snapLeft = dockSide === 'left' ? EDGE_GAP : Math.max(EDGE_GAP, vpW - AVATAR_PX_W - EDGE_GAP)
        this.setData({
          dragging: false,
          dockSide,
          leftPx: Math.round(snapLeft),
        })
        this.persistPosition({ dockSide, topPx: this.data.topPx })
        this._hasMoved = false
        return
      }
      this.onTapMascot()
    },

    onTapMascot() {
      this.triggerTapFeedback()
      const nextOpen = !this.data.drawerOpen
      this.setData({
        drawerOpen: nextOpen,
        bubbleText: nextOpen ? '' : this.data.bubbleText,
      })
    },

    onOpenFromBubble() {
      this.triggerTapFeedback()
      this.setData({
        drawerOpen: true,
        bubbleText: '',
      })
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
      this.triggerTapFeedback()
    },

    onCloseDrawer() {
      this.setData({ drawerOpen: false })
    },

    onResetTopic() {
      this.abortActiveStream()
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
      if (q) {
        this.sendPrompt(q)
      }
    },

    onSendInput() {
      this.sendPrompt(this.data.inputValue)
    },

    abortActiveStream() {
      if (this._streamHandle && typeof this._streamHandle.abort === 'function') {
        try {
          this._streamHandle.abort()
        } catch (_e) {
          // ignore abort errors
        }
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

      this.setData({ inputValue: '' })

      const userMsg = {
        id: `u_${Date.now()}`,
        role: 'user',
        content: text,
      }
      const aiMsg = {
        id: `a_${Date.now() + 1}`,
        role: 'assistant',
        content: '',
        favorited: false,
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
              if (!receivedCare && this._localMood === 'thinking') {
                this.setLocalMood('idle', 0)
              }
              if (this._draftBuffer) {
                this._draftBuffer.content += chunk
                this.scheduleFlush(aiIdx)
              }
            },
            onError: (errMsg) => {
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
        this.flushNow(aiIdx)
        if (!receivedCare && this._draftBuffer && this._draftBuffer.content) {
          this.setLocalMood('happy', 2400)
        }
      } catch (err) {
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
