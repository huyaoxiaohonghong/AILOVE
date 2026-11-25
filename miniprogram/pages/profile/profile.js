const env = require('../../config/env')
const auth = require('../../utils/auth')
const api = require('../../services/api')

Page({
  data: {
    userInfo: null,
    avatarInitial: '爱',
    maskedOpenid: '',
    loggingIn: false,
    quota: null,
    reqPercent: 0,
    tokPercent: 0,
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
  },

  onShow() {
    this.syncEnvState()
    this.syncLocalUser()
    this.refreshDashboard()
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
    let maskedOpenid = ''
    if (userInfo && userInfo.openid) {
      const oid = String(userInfo.openid)
      maskedOpenid = oid.length > 10 ? `${oid.slice(0, 6)}****${oid.slice(-4)}` : oid
    }
    this.setData({
      userInfo,
      avatarInitial,
      maskedOpenid,
      inviteLocked: Boolean(userInfo && userInfo.invite_required && !userInfo.invite_verified),
    })
  },

  async refreshDashboard() {
    this.checkHealth()
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
      let reqPercent = 0
      let tokPercent = 0
      if (quota) {
        if (quota.requests_limit > 0) {
          reqPercent = Math.min(100, Math.round((quota.requests_used * 100) / quota.requests_limit))
        }
        if (quota.tokens_limit > 0) {
          tokPercent = Math.min(100, Math.round((quota.tokens_used * 100) / quota.tokens_limit))
        }
      }
      this.setData({
        quota,
        reqPercent,
        tokPercent,
        loveProfile: lpRes && lpRes.profile ? lpRes.profile : null,
        conversationCount: convRes && convRes.items ? convRes.items.length : 0,
      })
    } catch (_e) {
      // 忽略
    }
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

  goReplyHelper() {
    wx.navigateTo({ url: '/pages/reply-helper/reply-helper' })
  },

  goSoftenDraft() {
    wx.navigateTo({ url: '/pages/soften-draft/soften-draft' })
  },

  goFavorites() {
    wx.navigateTo({ url: '/pages/favorites/favorites' })
  },

  goHistoryChat() {
    const app = getApp()
    app.setChatIntent({ openHistory: true })
    wx.switchTab({ url: '/pages/chat/chat' })
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
        this.setData({ quota: null, loveProfile: null, conversationCount: 0 })
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
        this.setData({ quota: null, loveProfile: null, conversationCount: 0 })
        wx.showToast({ title: '已退出登录', icon: 'none' })
      },
    })
  },
})
