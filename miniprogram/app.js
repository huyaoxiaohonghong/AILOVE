const env = require('./config/env')
const auth = require('./utils/auth')

App({
  globalData: {
    envName: env.ENV,
    apiBaseUrl: env.API_BASE_URL,
    userInfo: null,
    token: '',
  },

  onLaunch() {
    const token = auth.getToken()
    const userInfo = auth.getCachedUser()
    if (token && userInfo) {
      this.globalData.token = token
      this.globalData.userInfo = userInfo
    }
  },
})
