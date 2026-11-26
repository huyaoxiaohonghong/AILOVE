const api = require('../../services/api')
const auth = require('../../utils/auth')
const env = require('../../config/env')

const WELCOME_BUBBLE = {
  id: 1,
  role: 'assistant',
  modelLabel: 'AILOVE 恋爱情感助手',
  content:
    '你好呀！把你当下的心动、困惑或委屈都告诉我吧。\n\n• 顶部可随时切换 5 位专属恋爱导师\n• 点击「帮我回消息」可直接粘贴 TA 的原话拆解潜台词\n• 开启「情感档案」后，每次对话都会自动记住你的恋爱背景',
}

Page({
  data: {
    sessionId: '',
    personas: [],
    selectedPersonaId: null,
    activePersona: null,
    skills: [],
    selectedSkillIds: [],
    conversations: [],
    historyVisible: false,
    loadingHistory: false,
    loveProfileActive: false,
    loveProfileStage: '',
    quotaText: '',
    inputValue: '',
    sending: false,
    incognitoMode: false,
    mascotMood: '',
    scrollTop: 0,
    scrollToId: '',
    messages: [WELCOME_BUBBLE],
  },

  _streamHandle: null,
  _flushTimer: null,
  _pendingDraft: null,
  _mascotTimer: null,
  _initialized: false,
  _lastEnvKey: '',
  _scrollTick: 0,

  noop() {},

  setMascotMood(mood, resetMs) {
    if (this._mascotTimer) {
      clearTimeout(this._mascotTimer)
      this._mascotTimer = null
    }
    this.setData({ mascotMood: mood || '' })
    if (mood && resetMs > 0) {
      this._mascotTimer = setTimeout(() => {
        this.setData({ mascotMood: '' })
        this._mascotTimer = null
      }, resetMs)
    }
  },

  nextBottomScrollTop() {
    this._scrollTick += 1
    return 999999 + (this._scrollTick % 2)
  },

  onLoad() {
    this._lastEnvKey = env.getEnvConfig().ENV
    this.initChatPage()
  },

  onShow() {
    if (!this._initialized) return
    const currentEnv = env.getEnvConfig().ENV
    if (currentEnv !== this._lastEnvKey) {
      this._lastEnvKey = currentEnv
      this.resetToNewChat(null)
      this.setData({
        personas: [],
        conversations: [],
        loveProfileActive: false,
        loveProfileStage: '',
        quotaText: '',
      })
      this.initChatPage()
      return
    }
    if (!auth.getToken()) {
      this.setData({
        conversations: [],
        loveProfileActive: false,
        loveProfileStage: '',
        quotaText: '',
      })
      return
    }
    this.refreshLightMeta()
    this.loadSkills()
    this.applyPendingIntent()
  },

  onUnload() {
    this.stopStreamSilently()
    if (this._mascotTimer) {
      clearTimeout(this._mascotTimer)
      this._mascotTimer = null
    }
  },

  async initChatPage() {
    try {
      await auth.ensureLogin()
      await Promise.all([
        this.loadPersonas(),
        this.loadSkills(),
        this.loadConversations(),
        this.refreshLightMeta(),
      ])
    } catch (_e) {
      // 网络离线时保留欢迎气泡
    }
    this._initialized = true
    this.applyPendingIntent()
  },

  async loadPersonas() {
    try {
      const res = await api.getPersonas()
      const list = (res && res.items) || []
      this.setData({ personas: list })
      this.syncActivePersona(this.data.selectedPersonaId)
    } catch (_e) {
      // 忽略
    }
  },

  async loadSkills() {
    try {
      const res = await api.getKbSkills()
      const selected = new Set(this.data.selectedSkillIds || [])
      const items = ((res && res.items) || []).map((s) =>
        Object.assign({}, s, { _selected: selected.has(s.id) }),
      )
      this.setData({ skills: items })
    } catch (_e) {
      // 忽略
    }
  },

  onSelectSkill(e) {
    if (this.data.sending) return
    const rawId = e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.id
    if (!rawId) {
      const reset = (this.data.skills || []).map((s) => Object.assign({}, s, { _selected: false }))
      this.setData({ selectedSkillIds: [], skills: reset })
      return
    }
    const sid = Number(rawId)
    const cur = new Set(this.data.selectedSkillIds || [])
    if (cur.has(sid)) cur.delete(sid)
    else cur.add(sid)
    const nextIds = Array.from(cur).slice(0, 3)
    const updated = (this.data.skills || []).map((s) =>
      Object.assign({}, s, { _selected: nextIds.includes(s.id) }),
    )
    this.setData({ selectedSkillIds: nextIds, skills: updated })
  },

  async loadConversations() {
    try {
      const res = await api.getConversations()
      this.setData({ conversations: (res && res.items) || [] })
    } catch (_e) {
      // 忽略
    }
  },

  async refreshLightMeta() {
    try {
      const [lpRes, quotaRes] = await Promise.all([
        api.getLoveProfile().catch(() => null),
        api.getMyQuota().catch(() => null),
      ])
      const lp = lpRes && lpRes.profile
      const active = Boolean(lp && lp.is_configured && lp.auto_inject)
      let quotaText = ''
      if (quotaRes) {
        if (quotaRes.is_exempt) {
          quotaText = `今日 ${quotaRes.requests_used} 次`
        } else if (quotaRes.requests_limit > 0) {
          quotaText = `剩 ${quotaRes.requests_remaining}/${quotaRes.requests_limit}`
        }
      }
      this.setData({
        loveProfileActive: active,
        loveProfileStage: (lp && lp.relationship_stage_label) || '',
        quotaText,
      })
    } catch (_e) {
      // 忽略
    }
  },

  syncActivePersona(pid) {
    const matched = pid ? (this.data.personas || []).find((p) => p.id === pid) || null : null
    this.setData({
      selectedPersonaId: matched ? matched.id : null,
      activePersona: matched,
    })
  },

  async applyPendingIntent() {
    const app = getApp()
    const intent = app && app.consumeChatIntent ? app.consumeChatIntent() : null
    if (!intent) return

    if (intent.openHistory) {
      this.loadConversations()
      this.setData({ historyVisible: true })
      return
    }

    if (intent.sessionId) {
      await this.loadSessionById(intent.sessionId)
      return
    }

    if (intent.newChat) {
      this.resetToNewChat(intent.personaId || null)
    } else if (intent.personaId) {
      this.syncActivePersona(intent.personaId)
    }

    if (intent.promptText) {
      this.sendPrompt(intent.promptText)
    }
  },

  resetToNewChat(personaId) {
    this.stopStreamSilently()
    if (personaId !== undefined) {
      this.syncActivePersona(personaId)
    }
    const p = this.data.activePersona
    const greet = p
      ? `${p.avatar_emoji || '💘'} 你好，我是「${p.name}」。${p.description || '说说你想聊的心事吧。'}`
      : '已开启全新会话，把你的想法、困惑或对方说的话发给我吧。'
    this.setData({
      sessionId: '',
      messages: [
        {
          id: Date.now(),
          role: 'assistant',
          modelLabel: p ? p.name : 'AILOVE 恋爱情感助手',
          content: greet,
        },
      ],
    })
  },

  onSelectPersona(e) {
    if (this.data.sending) return
    const rawId = e.currentTarget.dataset.id
    const pid = rawId ? Number(rawId) : null
    this.syncActivePersona(pid)
  },

  onNewChatTap() {
    this.resetToNewChat(this.data.selectedPersonaId)
    wx.showToast({ title: '已开启新对话', icon: 'none' })
  },

  onOpenHistory() {
    this.loadConversations()
    this.setData({ historyVisible: true })
  },

  onCloseHistory() {
    this.setData({ historyVisible: false })
  },

  async onSelectHistoryItem(e) {
    const sid = e.currentTarget.dataset.sid
    if (!sid || this.data.sending) return
    this.setData({ historyVisible: false })
    await this.loadSessionById(sid)
  },

  async loadSessionById(sessionId) {
    this.stopStreamSilently()
    if (this.data.incognitoMode) {
      this.setData({ incognitoMode: false })
    }
    this.setData({ loadingHistory: true })
    try {
      const detail = await api.getConversationMessages(sessionId)
      this.syncActivePersona(detail.persona_id || null)
      const labelPrefix = detail.persona_name ? `${detail.persona_name} · ` : ''
      const mapped = (detail.messages || [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m, idx) => ({
          id: m.id || idx + 1,
          role: m.role,
          content: m.content,
          modelLabel: m.role === 'assistant' ? `${labelPrefix}${detail.model_name || 'AI'}` : '',
        }))
      const list = mapped.length > 0 ? mapped : [WELCOME_BUBBLE]
      const lastId = list[list.length - 1].id
      this.setData({
        sessionId: detail.session_id,
        messages: list,
        scrollToId: `msg-${lastId}`,
        scrollTop: this.nextBottomScrollTop(),
      })
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '加载历史会话失败', icon: 'none' })
    } finally {
      this.setData({ loadingHistory: false })
    }
  },

  async onTogglePinConv(e) {
    const sid = e.currentTarget.dataset.sid
    const pinned = Boolean(e.currentTarget.dataset.pinned)
    try {
      await api.updateConversation(sid, { is_pinned: !pinned })
      wx.showToast({ title: !pinned ? '已置顶' : '已取消置顶', icon: 'none' })
      await this.loadConversations()
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '操作失败', icon: 'none' })
    }
  },

  onDeleteConv(e) {
    const sid = e.currentTarget.dataset.sid
    const title = e.currentTarget.dataset.title || '该会话'
    wx.showModal({
      title: '删除会话',
      content: `确认删除「${title}」？删除后无法恢复。`,
      confirmColor: '#c83553',
      success: async (res) => {
        if (!res.confirm) return
        try {
          await api.deleteConversation(sid)
          if (this.data.sessionId === sid) {
            this.resetToNewChat(this.data.selectedPersonaId)
          }
          await this.loadConversations()
          wx.showToast({ title: '已删除', icon: 'none' })
        } catch (err) {
          wx.showToast({ title: (err && err.message) || '删除失败', icon: 'none' })
        }
      },
    })
  },

  goLoveProfile() {
    wx.navigateTo({ url: '/pages/love-profile/love-profile' })
  },

  goReplyHelper() {
    wx.navigateTo({ url: '/pages/reply-helper/reply-helper' })
  },

  goSoftenDraft() {
    wx.navigateTo({ url: '/pages/soften-draft/soften-draft' })
  },

  onToggleIncognito() {
    if (this.data.sending) return
    const next = !this.data.incognitoMode
    this.setData({ incognitoMode: next })
    if (next) {
      this.resetToNewChat(this.data.selectedPersonaId)
      wx.showToast({ title: '已开启无痕倾诉，本轮不存记录', icon: 'none' })
    } else {
      wx.showToast({ title: '已退出无痕模式', icon: 'none' })
    }
  },

  onInputChange(e) {
    this.setData({ inputValue: e.detail.value })
  },

  onTapStarter(e) {
    const txt = e.currentTarget.dataset.prompt
    if (txt && !this.data.sending) {
      this.sendPrompt(txt)
    }
  },

  handleSend() {
    const content = (this.data.inputValue || '').trim()
    if (!content || this.data.sending) return
    this.setData({ inputValue: '' })
    this.sendPrompt(content)
  },

  handleStop() {
    this.stopStreamSilently()
    const list = this.data.messages.slice()
    const last = list[list.length - 1]
    if (last && last.role === 'assistant') {
      last.content = last.content ? `${last.content}\n\n（已停止生成）` : '（已停止生成）'
      this.setData({ messages: list, sending: false })
    } else {
      this.setData({ sending: false })
    }
  },

  stopStreamSilently() {
    if (this._flushTimer) {
      clearTimeout(this._flushTimer)
      this._flushTimer = null
    }
    this._pendingDraft = null
    if (this._streamHandle) {
      this._streamHandle.abort()
      this._streamHandle = null
    }
  },

  scheduleDraftFlush(targetIndex) {
    if (this._flushTimer) return
    this._flushTimer = setTimeout(() => {
      this._flushTimer = null
      if (!this._pendingDraft) return
      const draft = this._pendingDraft
      const keyPrefix = `messages[${targetIndex}]`
      this.setData({
        [`${keyPrefix}.content`]: draft.content,
        [`${keyPrefix}.reasoning`]: draft.reasoning,
        [`${keyPrefix}.modelLabel`]: draft.modelLabel,
        [`${keyPrefix}.loveProfileInjected`]: draft.loveProfileInjected,
        [`${keyPrefix}.emotionCare`]: draft.emotionCare,
        [`${keyPrefix}.isError`]: draft.isError,
        scrollTop: this.nextBottomScrollTop(),
      })
    }, 75)
  },

  flushDraftNow(targetIndex) {
    if (this._flushTimer) {
      clearTimeout(this._flushTimer)
      this._flushTimer = null
    }
    if (!this._pendingDraft) return
    const draft = this._pendingDraft
    const keyPrefix = `messages[${targetIndex}]`
    this.setData({
      [`${keyPrefix}.content`]: draft.content,
      [`${keyPrefix}.reasoning`]: draft.reasoning,
      [`${keyPrefix}.modelLabel`]: draft.modelLabel,
      [`${keyPrefix}.loveProfileInjected`]: draft.loveProfileInjected,
      [`${keyPrefix}.emotionCare`]: draft.emotionCare,
      [`${keyPrefix}.invokedSkills`]: draft.invokedSkills || [],
      [`${keyPrefix}.isError`]: draft.isError,
      scrollTop: this.nextBottomScrollTop(),
    })
  },

  async sendPrompt(content) {
    if (!content || this.data.sending) return

    const userMsg = { id: Date.now(), role: 'user', content }
    const aiMsg = {
      id: Date.now() + 1,
      role: 'assistant',
      content: '',
      reasoning: '',
      reasoningOpen: false,
      modelLabel: this.data.activePersona ? this.data.activePersona.name : 'AILOVE AI',
      loveProfileInjected: false,
      emotionCare: null,
      invokedSkills: [],
      isError: false,
    }
    const nextList = this.data.messages.concat([userMsg, aiMsg])
    const aiIndex = nextList.length - 1
    this._pendingDraft = Object.assign({}, aiMsg)

    this.setData({
      messages: nextList,
      sending: true,
      scrollToId: 'chat-bottom-anchor',
      scrollTop: this.nextBottomScrollTop(),
    })
    this.setMascotMood('thinking', 0)

    let receivedCare = false
    try {
      await auth.ensureLogin()
      const isIncognito = Boolean(this.data.incognitoMode)
      const ephemeralHistory = isIncognito
        ? this.data.messages
            .slice(1, -2)
            .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content && !m.isError)
            .slice(-12)
            .map((m) => ({ role: m.role, content: m.content }))
        : undefined
      const payload = {
        message: content,
        session_id: this.data.sessionId || undefined,
        persona_id: this.data.selectedPersonaId || undefined,
        timezone: 'Asia/Shanghai',
        incognito: isIncognito,
        ephemeral_history: ephemeralHistory,
        skill_ids: this.data.selectedSkillIds || [],
        auto_match_skills: true,
      }

      const handle = api.streamAiChat(payload, {
        onMeta: (meta) => {
          this.setData({ sessionId: meta.session_id })
          if (this._pendingDraft) {
            const prefix = meta.persona_name ? `${meta.persona_name} · ` : ''
            this._pendingDraft.modelLabel = `${prefix}${meta.model || 'AI'}${meta.is_mock ? ' · 演示' : ''}`
            this._pendingDraft.loveProfileInjected = Boolean(meta.love_profile_injected)
            this._pendingDraft.emotionCare = meta.emotion_care || null
            this._pendingDraft.invokedSkills = meta.invoked_skills || []
            if (meta.emotion_care) {
              receivedCare = true
              this.setMascotMood('comfort', 5400)
            }
            this.scheduleDraftFlush(aiIndex)
          }
        },
        onFallback: (backupLabel) => {
          if (this._pendingDraft) {
            this._pendingDraft.modelLabel = `${backupLabel} · 自动容灾接管`
            this.scheduleDraftFlush(aiIndex)
          }
        },
        onReasoning: (chunk) => {
          if (this._pendingDraft) {
            this._pendingDraft.reasoning += chunk
            this.scheduleDraftFlush(aiIndex)
          }
        },
        onDelta: (chunk) => {
          if (!receivedCare && this.data.mascotMood === 'thinking') {
            this.setMascotMood('', 0)
          }
          if (this._pendingDraft) {
            this._pendingDraft.content += chunk
            this.scheduleDraftFlush(aiIndex)
          }
        },
        onError: (errMsg) => {
          if (this._pendingDraft) {
            this._pendingDraft.isError = true
            this._pendingDraft.content = this._pendingDraft.content
              ? `${this._pendingDraft.content}\n\n⚠️ ${errMsg}`
              : `⚠️ ${errMsg}`
            this.flushDraftNow(aiIndex)
          }
          this.setMascotMood('comfort', 3000)
        },
      })

      this._streamHandle = handle
      await handle.promise
      this.flushDraftNow(aiIndex)
      if (!receivedCare && this._pendingDraft && !this._pendingDraft.isError && this._pendingDraft.content) {
        this.setMascotMood('happy', 2400)
      }
      this.loadConversations()
      this.refreshLightMeta()
    } catch (err) {
      if (this._pendingDraft) {
        this._pendingDraft.isError = true
        this._pendingDraft.content = `请求出错：${(err && err.message) || '请检查网络连接'}`
        this.flushDraftNow(aiIndex)
      }
      this.setMascotMood('comfort', 3000)
    } finally {
      this._streamHandle = null
      this._pendingDraft = null
      this.setData({ sending: false })
    }
  },

  onToggleReasoning(e) {
    const idx = Number(e.currentTarget.dataset.idx)
    const cur = this.data.messages[idx]
    if (!cur) return
    this.setData({
      [`messages[${idx}].reasoningOpen`]: !cur.reasoningOpen,
    })
  },

  onCopyMessage(e) {
    const txt = e.currentTarget.dataset.content || ''
    if (!txt) return
    wx.setClipboardData({
      data: txt,
      success() {
        wx.showToast({ title: '已复制到剪贴板', icon: 'success' })
      },
    })
  },

  async onFavoriteMessage(e) {
    const txt = (e.currentTarget.dataset.content || '').trim()
    const label = (e.currentTarget.dataset.label || '').trim() || 'AI 咨询'
    if (!txt) return
    try {
      const res = await api.saveFavorite({
        content: txt.slice(0, 1200),
        category: 'chat',
        scene_label: label.slice(0, 64),
      })
      this.setMascotMood('happy', 2200)
      wx.showToast({
        title: res && res.deduplicated ? '已在收藏夹中' : '已收藏到话术库',
        icon: 'success',
      })
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '收藏失败', icon: 'none' })
    }
  },

  onTapHotline(e) {
    const phone = String(e.currentTarget.dataset.phone || '').trim()
    if (!phone) return
    const cleanNum = phone.split('/')[0].trim()
    wx.showActionSheet({
      itemList: [`拨打 ${cleanNum}`, `复制号码 ${phone}`],
      success(res) {
        if (res.tapIndex === 0) {
          wx.makePhoneCall({ phoneNumber: cleanNum })
        } else {
          wx.setClipboardData({
            data: phone,
            success() {
              wx.showToast({ title: '号码已复制', icon: 'success' })
            },
          })
        }
      },
    })
  },
})
