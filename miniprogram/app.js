const env = require('./config/env')
const auth = require('./utils/auth')

App({
  globalData: {
    envName: env.getEnvConfig().ENV,
    apiBaseUrl: env.getEnvConfig().API_BASE_URL,
    userInfo: null,
    token: '',
    // switchTab 不支持 query 参数，使用内存意图对象跨页无缝传递目标智能体或会话
    pendingChatIntent: null,
  },

  onLaunch() {
    this.syncEnv()
    const token = auth.getToken()
    const userInfo = auth.getCachedUser()
    if (token && userInfo) {
      this.globalData.token = token
      this.globalData.userInfo = userInfo
    }
  },

  syncEnv() {
    const cfg = env.getEnvConfig()
    this.globalData.envName = cfg.ENV
    this.globalData.apiBaseUrl = cfg.API_BASE_URL
    return cfg
  },

  setChatIntent(intent) {
    this.globalData.pendingChatIntent = intent || null
  },

  consumeChatIntent() {
    const intent = this.globalData.pendingChatIntent
    this.globalData.pendingChatIntent = null
    return intent
  },
})
