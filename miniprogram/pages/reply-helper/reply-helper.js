const api = require('../../services/api')
const auth = require('../../utils/auth')

const DEFAULT_SCENES = [
  { code: 'ambiguous', label: '暧昧升温', desc: '试探心意、自然拉近距离' },
  { code: 'cold_reply', label: '对方冷淡', desc: '回复敷衍、间隔变长怎么破局' },
  { code: 'conflict', label: '吵架哄人', desc: '情绪降温、体面化解僵局' },
  { code: 'date_invite', label: '约会邀约', desc: '发出或回应见面邀约' },
  { code: 'polite_decline', label: '体面婉拒', desc: '温和守边界、不伤和气' },
]

const DEFAULT_TONES = [
  { code: 'playful', label: '俏皮拉扯', desc: '轻幽默带点小反问，留出聊天钩子' },
  { code: 'gentle', label: '温柔体贴', desc: '先接住对方情绪，温暖有安全感' },
  { code: 'graceful', label: '体面台阶', desc: '不卑不亢，给彼此舒适退路' },
  { code: 'sincere', label: '真诚直球', desc: '坦荡清晰表达想法，减少猜忌内耗' },
  { code: 'humorous', label: '幽默破冰', desc: '轻松调侃化解尴尬或沉默' },
]

function extractQuotedReplies(markdownText) {
  if (!markdownText) return []
  const lines = markdownText.split('\n')
  const items = []
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim()
    if (line.indexOf('>') === 0) {
      const clean = line.replace(/^>+\s*/, '').replace(/^["「『]+|["」』]+$/g, '').trim()
      if (clean && clean.length >= 4 && clean.length <= 220) {
        items.push(clean)
      }
    }
    if (items.length >= 4) break
  }
  return items
}

Page({
  data: {
    partnerMessage: '',
    scene: 'ambiguous',
    tone: 'playful',
    myIntent: '',
    context: '',
    scenes: DEFAULT_SCENES,
    tones: DEFAULT_TONES,
    loveProfileActive: false,
    generating: false,
    resultSessionId: '',
    resultText: '',
    resultLabel: '',
    suggestedReplies: [],
    emotionCare: null,
    errorText: '',
  },

  _streamHandle: null,
  _flushTimer: null,
  _draftText: '',

  onLoad() {
    this.loadMeta()
  },

  onUnload() {
    this.stopGeneration()
  },

  async loadMeta() {
    try {
      await auth.ensureLogin()
      const [presets, lpRes] = await Promise.all([
        api.getReplyHelperPresets().catch(() => null),
        api.getLoveProfile().catch(() => null),
      ])
      const lp = lpRes && lpRes.profile
      this.setData({
        scenes: (presets && presets.scenes && presets.scenes.length) ? presets.scenes : DEFAULT_SCENES,
        tones: (presets && presets.tones && presets.tones.length) ? presets.tones : DEFAULT_TONES,
        loveProfileActive: Boolean(lp && lp.is_configured && lp.auto_inject),
      })
    } catch (_e) {
      // 使用内置预设
    }
  },

  onPasteClipboard() {
    wx.getClipboardData({
      success: (res) => {
        const text = (res.data || '').trim()
        if (!text) {
          wx.showToast({ title: '剪贴板为空', icon: 'none' })
          return
        }
        this.setData({ partnerMessage: text.slice(0, 2000) })
        wx.showToast({ title: '已粘贴对方原话', icon: 'success' })
      },
    })
  },

  onPartnerInput(e) {
    this.setData({ partnerMessage: e.detail.value })
  },

  onIntentInput(e) {
    this.setData({ myIntent: e.detail.value })
  },

  onContextInput(e) {
    this.setData({ context: e.detail.value })
  },

  onSelectScene(e) {
    this.setData({ scene: e.currentTarget.dataset.code })
  },

  onSelectTone(e) {
    this.setData({ tone: e.currentTarget.dataset.code })
  },

  stopGeneration() {
    if (this._flushTimer) {
      clearTimeout(this._flushTimer)
      this._flushTimer = null
    }
    if (this._streamHandle) {
      this._streamHandle.abort()
      this._streamHandle = null
    }
  },

  scheduleFlush() {
    if (this._flushTimer) return
    this._flushTimer = setTimeout(() => {
      this._flushTimer = null
      this.setData({
        resultText: this._draftText,
        suggestedReplies: extractQuotedReplies(this._draftText),
      })
    }, 80)
  },

  async handleGenerate() {
    const msg = (this.data.partnerMessage || '').trim()
    if (!msg) {
      wx.showToast({ title: '请先粘贴或输入对方发来的原话', icon: 'none' })
      return
    }
    if (this.data.generating) return

    this.stopGeneration()
    this._draftText = ''
    this.setData({
      generating: true,
      resultText: '',
      resultSessionId: '',
      resultLabel: '高情商恋爱军师 · 正在拆解潜台词...',
      suggestedReplies: [],
      emotionCare: null,
      errorText: '',
    })

    try {
      await auth.ensureLogin()
      const handle = api.streamReplyHelper(
        {
          partner_message: msg,
          scene: this.data.scene,
          tone: this.data.tone,
          my_intent: (this.data.myIntent || '').trim(),
          context: (this.data.context || '').trim(),
          timezone: 'Asia/Shanghai',
        },
        {
          onMeta: (meta) => {
            const pName = meta.persona_name || '高情商恋爱军师'
            this.setData({
              resultSessionId: meta.session_id || '',
              resultLabel: `${pName} · ${meta.model || 'AI'}${meta.love_profile_injected ? ' · 已结合情感档案' : ''}`,
              emotionCare: meta.emotion_care || null,
            })
          },
          onFallback: (backupLabel) => {
            this.setData({ resultLabel: `${backupLabel} · 自动容灾接管` })
          },
          onDelta: (chunk) => {
            this._draftText += chunk
            this.scheduleFlush()
          },
          onError: (errMsg) => {
            this.setData({ errorText: errMsg })
          },
        }
      )
      this._streamHandle = handle
      await handle.promise
      if (this._flushTimer) {
        clearTimeout(this._flushTimer)
        this._flushTimer = null
      }
      this.setData({
        resultText: this._draftText,
        suggestedReplies: extractQuotedReplies(this._draftText),
      })
    } catch (err) {
      this.setData({
        errorText: (err && err.message) || '生成失败，请检查网络连接',
      })
    } finally {
      this._streamHandle = null
      this.setData({ generating: false })
    }
  },

  onCopyText(e) {
    const txt = e.currentTarget.dataset.text || ''
    if (!txt) return
    wx.setClipboardData({
      data: txt,
      success() {
        wx.showToast({ title: '已复制，可直接去微信粘贴', icon: 'success' })
      },
    })
  },

  onContinueInChat() {
    const sid = this.data.resultSessionId
    if (!sid) return
    const app = getApp()
    app.setChatIntent({ sessionId: sid })
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  goLoveProfile() {
    wx.navigateTo({ url: '/pages/love-profile/love-profile' })
  },
})
