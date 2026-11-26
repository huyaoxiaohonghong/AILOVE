const env = require('../../config/env')
const auth = require('../../utils/auth')
const api = require('../../services/api')

Page({
  data: {
    userInfo: null,
    avatarInitial: '爱',
    loggingIn: false,
    quotaSummary: '',
    loveProfile: null,
    conversationCount: 0,
    envKey: 'cloud',
    envLabel: '云端测试服',
    apiBaseUrl: '',
    healthType: 'info',
    healthText: '未检测',
    healthModel: '-',
    inviteLocked: false,
    inviteInput: '',
    verifyingInvite: false,
    devPanelVisible: false,
  },

  _footerTapCount: 0,
  _footerTapTimer: null,

  noop() {},

  onShow() {
    this.syncEnvState()
    this.syncLocalUser()
    this.refreshDashboard()
  },

  onUnload() {
    if (this._footerTapTimer) {
      clearTimeout(this._footerTapTimer)
      this._footerTapTimer = null
    }
  },

  onInviteInput(e) {
    this.setData({ inviteInput: e.detail.value })
  },

  async handleVerifyInvite() {
    const code = (this.data.inviteInput || '').trim()
    if (!code) {
      wx.showToast({ title: '请输入内测邀请码', icon: 'none' })
      return
    }
    if (this.data.verifyingInvite) return
    this.setData({ verifyingInvite: true })
    try {
      const updated = await api.verifyInviteCode(code)
      auth.saveSession(auth.getToken(), updated)
      this.syncLocalUser()
      this.setData({ inviteLocked: false, inviteInput: '' })
      wx.showToast({ title: '邀请码激活成功', icon: 'success' })
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '邀请码无效', icon: 'none' })
    } finally {
      this.setData({ verifyingInvite: false })
    }
  },

  onPullDownRefresh() {
    this.refreshDashboard().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  syncEnvState() {
    const cfg = env.getEnvConfig()
    this.setData({
      envKey: cfg.ENV,
      envLabel: cfg.LABEL || cfg.ENV,
      apiBaseUrl: cfg.API_BASE_URL,
    })
  },

  syncLocalUser() {
    const userInfo = auth.getCachedUser()
    const avatarInitial =
      userInfo && userInfo.nickname ? userInfo.nickname.slice(0, 1) : '爱'
    this.setData({
      userInfo,
      avatarInitial,
      inviteLocked: Boolean(userInfo && userInfo.invite_required && !userInfo.invite_verified),
    })
  },

  async refreshDashboard() {
    if (!auth.getToken()) return
    try {
      const [profile, quota, lpRes, convRes] = await Promise.all([
        api.getUserProfile().catch(() => null),
        api.getMyQuota().catch(() => null),
        api.getLoveProfile().catch(() => null),
        api.getConversations().catch(() => null),
      ])
      if (profile) {
        auth.saveSession(auth.getToken(), profile)
        this.syncLocalUser()
      }
      let quotaSummary = ''
      if (quota) {
        if (quota.is_exempt) {
          quotaSummary = `今日已陪伴咨询 ${quota.requests_used} 次`
        } else if (quota.requests_limit > 0) {
          quotaSummary = `今日剩余 ${quota.requests_remaining}/${quota.requests_limit} 次咨询`
        }
      }
      this.setData({
        quotaSummary,
        loveProfile: lpRes && lpRes.profile ? lpRes.profile : null,
        conversationCount: convRes && convRes.items ? convRes.items.length : 0,
      })
    } catch (_e) {
      // 忽略
    }
  },

  onTapVersionFooter() {
    this._footerTapCount += 1
    if (this._footerTapTimer) clearTimeout(this._footerTapTimer)
    if (this._footerTapCount >= 5) {
      this._footerTapCount = 0
      this._footerTapTimer = null
      this.syncEnvState()
      this.setData({ devPanelVisible: true })
      this.checkHealth()
      return
    }
    this._footerTapTimer = setTimeout(() => {
      this._footerTapCount = 0
      this._footerTapTimer = null
    }, 2500)
  },

  onCloseDevPanel() {
    this.setData({ devPanelVisible: false })
  },

  async checkHealth() {
    this.setData({ healthType: 'info', healthText: '检测中' })
    try {
      const data = await api.getHealth()
      const ok = data && data.status === 'ok'
      this.setData({
        healthType: ok ? 'success' : 'warning',
        healthText: ok ? '服务在线' : '降级运行',
        healthModel: (data && data.services && data.services.langchain && data.services.langchain.model) || '-',
      })
    } catch (_e) {
      this.setData({
        healthType: 'danger',
        healthText: '连接失败',
        healthModel: '-',
      })
    }
  },

  async handleWxLogin() {
    if (this.data.loggingIn) return
    this.setData({ loggingIn: true })
    try {
      const res = await auth.wxLogin()
      this.syncLocalUser()
      await this.refreshDashboard()
      wx.showToast({
        title: res.is_mock_wx ? '开发模式登录成功' : '登录成功',
        icon: 'success',
      })
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '登录失败', icon: 'none' })
    } finally {
      this.setData({ loggingIn: false })
    }
  },

  handleEditNickname() {
    if (!this.data.userInfo) {
      this.handleWxLogin()
      return
    }
    wx.showModal({
      title: '修改我的昵称',
      editable: true,
      placeholderText: '请输入新的昵称（1~32字）',
      content: this.data.userInfo.nickname || '',
      confirmColor: '#c83553',
      success: async (res) => {
        if (!res.confirm) return
        const nextName = (res.content || '').trim()
        if (!nextName) {
          wx.showToast({ title: '昵称不能为空', icon: 'none' })
          return
        }
        try {
          const updated = await api.updateUserProfile({ nickname: nextName })
          auth.saveSession(auth.getToken(), updated)
          this.syncLocalUser()
          wx.showToast({ title: '昵称已更新', icon: 'success' })
        } catch (err) {
          wx.showToast({ title: (err && err.message) || '更新失败', icon: 'none' })
        }
      },
    })
  },

  goLoveProfile() {
    wx.navigateTo({ url: '/pages/love-profile/love-profile' })
  },

  goFavorites() {
    wx.navigateTo({ url: '/pages/favorites/favorites' })
  },

  goHistoryChat() {
    const app = getApp()
    app.setChatIntent({ openHistory: true })
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  onOpenPrivacySheet() {
    wx.showActionSheet({
      itemList: ['导出私密情感手账 (.md)', '彻底清空个人云端数据'],
      success: (res) => {
        if (res.tapIndex === 0) {
          this.handleExportJournal()
        } else if (res.tapIndex === 1) {
          this.handlePurgeAllData()
        }
      },
    })
  },

  async handleExportJournal() {
    wx.showLoading({ title: '正在生成情感手账...' })
    try {
      const res = await api.exportMyJournalJson()
      wx.hideLoading()
      const md = (res && res.markdown) || ''
      const stats = (res && res.stats) || {}
      wx.setClipboardData({
        data: md,
        success() {
          wx.showModal({
            title: '私密情感手账已复制',
            content: `已将 ${stats.conversation_count || 0} 个会话、${stats.favorite_count || 0} 条收藏话术整理为 Markdown 并写入剪贴板，可直接粘贴保存到备忘录或微信收藏。`,
            showCancel: false,
            confirmColor: '#c83553',
          })
        },
      })
    } catch (err) {
      wx.hideLoading()
      wx.showToast({ title: (err && err.message) || '导出失败', icon: 'none' })
    }
  },

  handlePurgeAllData() {
    wx.showModal({
      title: '彻底清空个人云端数据',
      content: '确认永久删除全部历史对话、情感档案记忆卡与话术收藏？删除后不可恢复。',
      confirmText: '彻底清空',
      confirmColor: '#dc2626',
      success: async (res) => {
        if (!res.confirm) return
        try {
          await api.purgeMyData()
          this.setData({ loveProfile: null, conversationCount: 0 })
          wx.showToast({ title: '云端私密数据已彻底清空', icon: 'success' })
        } catch (err) {
          wx.showToast({ title: (err && err.message) || '清除失败', icon: 'none' })
        }
      },
    })
  },

  handleSwitchEnv() {
    const nextKey = this.data.envKey === 'cloud' ? 'local' : 'cloud'
    const nextCfg = env.ENV_PRESETS[nextKey]
    wx.showModal({
      title: '切换后端环境',
      content: `将接口地址切换至「${nextCfg.LABEL}」(${nextCfg.API_BASE_URL})？切换后需重新登录。`,
      confirmColor: '#c83553',
      success: (res) => {
        if (!res.confirm) return
        env.setEnvOverride(nextKey)
        const app = getApp()
        if (app && app.syncEnv) app.syncEnv()
        auth.logout()
        this.syncEnvState()
        this.syncLocalUser()
        this.setData({ quotaSummary: '', loveProfile: null, conversationCount: 0 })
        this.checkHealth()
        wx.showToast({ title: `已切换至${nextCfg.LABEL}`, icon: 'none' })
      },
    })
  },

  handleLogout() {
    wx.showModal({
      title: '退出登录',
      content: '确认退出当前微信登录会话？',
      confirmColor: '#c83553',
      success: (res) => {
        if (!res.confirm) return
        auth.logout()
        this.syncLocalUser()
        this.setData({ quotaSummary: '', loveProfile: null, conversationCount: 0 })
        wx.showToast({ title: '已退出登录', icon: 'none' })
      },
    })
  },
})
