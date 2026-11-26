const api = require('../../services/api')
const auth = require('../../utils/auth')

const DEFAULT_INTENSITIES = [
  { code: 'mild', label: '有点委屈', desc: '心里酸酸的，想温柔表达感受不被忽略' },
  { code: 'medium', label: '明显生气', desc: '有些火大或失望，想守住底线但不想翻脸' },
  { code: 'heated', label: '快上头了', desc: '差点把狠话/反话发出去，急需冷静降温' },
]

function extractQuotedReplies(markdownText) {
  if (!markdownText) return []
  const lines = markdownText.split('\n')
  const items = []
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim()
    if (line.indexOf('>') === 0) {
      const clean = line.replace(/^>+\s*/, '').replace(/^["「『]+|["」』]+$/g, '').trim()
      if (clean && clean.length >= 4 && clean.length <= 240) {
        items.push(clean)
      }
    }
    if (items.length >= 4) break
  }
  return items
}

Page({
  data: {
    draftMessage: '',
    intensity: 'heated',
    context: '',
    intensities: DEFAULT_INTENSITIES,
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
    this.applyToolIntent()
  },

  onShow() {
    this.applyToolIntent()
  },

  applyToolIntent() {
    const app = getApp()
    const intent = app && typeof app.consumeToolIntent === 'function' ? app.consumeToolIntent() : null
    if (!intent || intent.type !== 'open_soften_draft') return
    const patch = {}
    if (intent.draft_message) patch.draftMessage = String(intent.draft_message).slice(0, 2000)
    if (intent.intensity) patch.intensity = intent.intensity
    if (Object.keys(patch).length > 0) {
      this.setData(patch)
      wx.showToast({ title: '恋恋已为你带入草稿 🧊', icon: 'none' })
    }
  },

  onUnload() {
    this.stopGeneration()
  },

  async loadMeta() {
    try {
      await auth.ensureLogin()
      const res = await api.getSoftenPresets().catch(() => null)
      if (res && res.intensities && res.intensities.length) {
        this.setData({ intensities: res.intensities })
      }
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
        this.setData({ draftMessage: text.slice(0, 2000) })
        wx.showToast({ title: '已粘贴草稿', icon: 'success' })
      },
    })
  },

  onDraftInput(e) {
    this.setData({ draftMessage: e.detail.value })
  },

  onContextInput(e) {
    this.setData({ context: e.detail.value })
  },

  onSelectIntensity(e) {
    this.setData({ intensity: e.currentTarget.dataset.code })
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
    const msg = (this.data.draftMessage || '').trim()
    if (!msg) {
      wx.showToast({ title: '先把差点发出去的话粘贴进来吧', icon: 'none' })
      return
    }
    if (this.data.generating) return

    this.stopGeneration()
    this._draftText = ''
    this.setData({
      generating: true,
      resultText: '',
      resultSessionId: '',
      resultLabel: '吵架降温调解员 · 正在帮你冷静拆解...',
      suggestedReplies: [],
      emotionCare: null,
      errorText: '',
    })

    try {
      await auth.ensureLogin()
      const handle = api.streamSoftenDraft(
        {
          draft_message: msg,
          intensity: this.data.intensity,
          context: (this.data.context || '').trim(),
          timezone: 'Asia/Shanghai',
        },
        {
          onMeta: (meta) => {
            const pName = meta.persona_name || '吵架降温调解员'
            this.setData({
              resultSessionId: meta.session_id || '',
              resultLabel: `${pName}${meta.love_profile_injected ? ' · 已结合情感档案' : ''}`,
              emotionCare: meta.emotion_care || null,
            })
          },
          onFallback: () => {
            this.setData({ resultLabel: '吵架降温调解员 · 备用线路' })
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
        wx.showToast({ title: '已复制，深呼吸后再发', icon: 'success' })
      },
    })
  },

  async onFavoriteText(e) {
    const txt = (e.currentTarget.dataset.text || '').trim()
    if (!txt) return
    const lv = this.data.intensities.find((i) => i.code === this.data.intensity)
    try {
      const res = await api.saveFavorite({
        content: txt,
        category: 'soften',
        scene_label: lv ? `先别发 · ${lv.label}` : '先别发柔化',
      })
      wx.showToast({
        title: res && res.deduplicated ? '已在收藏夹中' : '已收藏到话术库',
        icon: 'success',
      })
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '收藏失败', icon: 'none' })
    }
  },

  onContinueInChat() {
    const sid = this.data.resultSessionId
    if (!sid) return
    const app = getApp()
    app.setChatIntent({ sessionId: sid })
    wx.switchTab({ url: '/pages/chat/chat' })
  },
})
