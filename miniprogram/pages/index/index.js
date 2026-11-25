const api = require('../../services/api')
const auth = require('../../utils/auth')
const env = require('../../config/env')

const CATEGORIES = [
  { key: 'all', label: '全部导师' },
  { key: 'chat_coach', label: '聊天话术' },
  { key: 'dating', label: '心动约会' },
  { key: 'relationship', label: '亲密关系' },
  { key: 'conflict', label: '矛盾修复' },
  { key: 'healing', label: '情绪疗愈' },
]

Page({
  data: {
    loading: true,
    errorMsg: '',
    userInfo: null,
    announcement: '',
    loveProfile: null,
    quotaText: '',
    categories: CATEGORIES,
    activeCategory: 'all',
    allPersonas: [],
    filteredPersonas: [],
    recentConversations: [],
  },

  _lastEnvKey: '',

  onLoad() {
    this._lastEnvKey = env.getEnvConfig().ENV
    this.bootstrapHome()
  },

  onShow() {
    const currentEnv = env.getEnvConfig().ENV
    const cached = auth.getCachedUser()
    this.setData({ userInfo: cached || null })

    if (currentEnv !== this._lastEnvKey) {
      this._lastEnvKey = currentEnv
      this.setData({
        allPersonas: [],
        filteredPersonas: [],
        recentConversations: [],
        loveProfile: null,
        quotaText: '',
      })
      this.bootstrapHome()
      return
    }

    if (!auth.getToken()) {
      this.setData({
        recentConversations: [],
        loveProfile: null,
        quotaText: '',
      })
      return
    }

    if (!this.data.loading) {
      this.refreshDynamicCards()
    }
  },

  onPullDownRefresh() {
    this.bootstrapHome().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async bootstrapHome() {
    this.setData({ loading: true, errorMsg: '' })
    try {
      const user = await auth.ensureLogin()
      this.setData({ userInfo: user })
      await this.refreshDynamicCards()
    } catch (err) {
      this.setData({
        errorMsg: (err && err.message) || '暂未连接到 AILOVE 云端服务，请下拉重试',
      })
    } finally {
      this.setData({ loading: false })
    }
  },

  async refreshDynamicCards() {
    try {
      const [pubCfg, personasRes, loveRes, convRes, quotaRes] = await Promise.all([
        api.getPublicConfig().catch(() => null),
        api.getPersonas().catch(() => ({ items: [] })),
        api.getLoveProfile().catch(() => null),
        api.getConversations().catch(() => ({ items: [] })),
        api.getMyQuota().catch(() => null),
      ])

      const allPersonas = (personasRes && personasRes.items) || []
      const recent = ((convRes && convRes.items) || []).slice(0, 3)
      let quotaText = ''
      if (quotaRes) {
        if (quotaRes.is_exempt) {
          quotaText = `今日已咨询 ${quotaRes.requests_used} 次`
        } else if (quotaRes.requests_limit > 0) {
          quotaText = `今日剩余 ${quotaRes.requests_remaining}/${quotaRes.requests_limit} 次`
        }
      }

      this.setData({
        errorMsg: '',
        announcement: (pubCfg && pubCfg.announcement) || '',
        allPersonas,
        loveProfile: loveRes && loveRes.profile ? loveRes.profile : null,
        recentConversations: recent,
        quotaText,
      })
      this.applyCategoryFilter(this.data.activeCategory)
    } catch (err) {
      this.setData({
        errorMsg: (err && err.message) || '加载数据失败，请下拉刷新',
      })
    }
  },

  applyCategoryFilter(catKey) {
    const all = this.data.allPersonas || []
    const list = catKey === 'all' ? all : all.filter((p) => p.category === catKey)
    this.setData({
      activeCategory: catKey,
      filteredPersonas: list,
    })
  },

  onSelectCategory(e) {
    const key = e.currentTarget.dataset.key || 'all'
    this.applyCategoryFilter(key)
  },

  goReplyHelper() {
    wx.navigateTo({ url: '/pages/reply-helper/reply-helper' })
  },

  goLoveProfile() {
    wx.navigateTo({ url: '/pages/love-profile/love-profile' })
  },

  goFreeChat() {
    const app = getApp()
    app.setChatIntent({ newChat: true })
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  onTapPersona(e) {
    const pid = Number(e.currentTarget.dataset.id)
    if (!pid) return
    const app = getApp()
    app.setChatIntent({ personaId: pid, newChat: true })
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  onTapStarter(e) {
    const pid = Number(e.currentTarget.dataset.id)
    const promptText = e.currentTarget.dataset.prompt || ''
    if (!promptText) return
    const app = getApp()
    app.setChatIntent({ personaId: pid || undefined, promptText, newChat: true })
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  onTapConversation(e) {
    const sid = e.currentTarget.dataset.sid
    if (!sid) return
    const app = getApp()
    app.setChatIntent({ sessionId: sid })
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  onOpenHistoryTab() {
    const app = getApp()
    app.setChatIntent({ openHistory: true })
    wx.switchTab({ url: '/pages/chat/chat' })
  },
})
