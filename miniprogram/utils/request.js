const env = require('../config/env')

const TOKEN_KEY = 'ailove_wx_token'
const USER_KEY = 'ailove_wx_user'

function getToken() {
  return wx.getStorageSync(TOKEN_KEY) || ''
}

function clearAuthStorage() {
  wx.removeStorageSync(TOKEN_KEY)
  wx.removeStorageSync(USER_KEY)
}

/**
 * 统一封装 wx.request，自动注入 Authorization 并解包后端统一结构 { code, message, data }
 */
function request(options) {
  const {
    url,
    method = 'GET',
    data = {},
    header = {},
    needAuth = true,
    timeout = 60000,
  } = options

  const token = getToken()
  const baseUrl = env.getEnvConfig().API_BASE_URL
  const mergedHeader = Object.assign(
    { 'Content-Type': 'application/json' },
    header,
    needAuth && token ? { Authorization: `Bearer ${token}` } : {}
  )

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${baseUrl}${url}`,
      method,
      data,
      timeout,
      header: mergedHeader,
      success(res) {
        const statusCode = res.statusCode
        const body = res.data || {}

        if (statusCode === 401) {
          clearAuthStorage()
          const app = getApp()
          if (app && app.globalData) {
            app.globalData.token = ''
            app.globalData.userInfo = null
          }
          reject(new Error(body.message || '登录已过期，请重新登录'))
          return
        }

        if (statusCode >= 200 && statusCode < 300 && body.code === 0) {
          resolve(body.data)
          return
        }

        reject(new Error(body.message || `请求失败 (${statusCode})`))
      },
      fail(err) {
        reject(new Error(err.errMsg || '网络连接失败，请检查网络或切换服务端地址'))
      },
    })
  })
}

module.exports = {
  request,
  getToken,
  clearAuthStorage,
  TOKEN_KEY,
  USER_KEY,
}
