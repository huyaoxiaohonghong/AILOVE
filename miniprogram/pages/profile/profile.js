const env = require('../../config/env')
const auth = require('../../utils/auth')
const api = require('../../services/api')

Page({
  data: {
    userInfo: null,
    avatarInitial: 'AI',
    loggingIn: false,
    envName: env.ENV,
    apiBaseUrl: env.API_BASE_URL,
  },

  onShow() {
    this.syncLocalUser()
  },

  syncLocalUser() {
    const userInfo = auth.getCachedUser()
    const avatarInitial = userInfo && userInfo.nickname ? userInfo.nickname.slice(0, 1) : 'AI'
    this.setData({ userInfo, avatarInitial })
  },

  async handleWxLogin() {
    if (this.data.loggingIn) return
    this.setData({ loggingIn: true })
    try {
      const res = await auth.wxLogin()
      this.syncLocalUser()
      wx.showToast({
        title: res.is_mock_wx ? '开发模式登录成功' : '登录成功',
        icon: 'success',
      })
    } catch (err) {
      wx.showToast({
        title: err.message || '登录失败',
        icon: 'none',
      })
    } finally {
      this.setData({ loggingIn: false })
    }
  },

  async handleRefreshProfile() {
    try {
      const profile = await api.getUserProfile()
      auth.saveSession(auth.getToken(), profile)
      this.syncLocalUser()
      wx.showToast({ title: '已同步资料', icon: 'success' })
    } catch (err) {
      wx.showToast({ title: err.message || '同步失败', icon: 'none' })
    }
  },

  handleLogout() {
    auth.logout()
    this.syncLocalUser()
    wx.showToast({ title: '已退出登录', icon: 'none' })
  },
})
