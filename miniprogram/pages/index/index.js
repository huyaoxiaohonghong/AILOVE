const env = require('../../config/env')
const api = require('../../services/api')

Page({
  data: {
    apiBaseUrl: env.API_BASE_URL,
    backendBadgeType: 'info',
    backendStatusText: '检测中',
    mysqlStatus: '-',
    redisStatus: '-',
    llmModel: '-',
  },

  onLoad() {
    this.checkBackendHealth()
  },

  onPullDownRefresh() {
    this.checkBackendHealth().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async checkBackendHealth() {
    this.setData({
      backendBadgeType: 'info',
      backendStatusText: '检测中',
    })
    try {
      const data = await api.getHealth()
      const isOk = data.status === 'ok'
      this.setData({
        backendBadgeType: isOk ? 'success' : 'warning',
        backendStatusText: isOk ? '运行正常' : '降级运行',
        mysqlStatus: data.services.mysql.status,
        redisStatus: data.services.redis.status,
        llmModel: data.services.langchain.model,
      })
    } catch (err) {
      this.setData({
        backendBadgeType: 'danger',
        backendStatusText: '未连接',
        mysqlStatus: '离线',
        redisStatus: '离线',
        llmModel: '-',
      })
      wx.showToast({
        title: err.message || '后端未连接',
        icon: 'none',
      })
    }
  },

  goChat() {
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  goProfile() {
    wx.switchTab({ url: '/pages/profile/profile' })
  },
})
