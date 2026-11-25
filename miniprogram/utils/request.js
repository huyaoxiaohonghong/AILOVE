const env = require('../config/env')

const TOKEN_KEY = 'ailove_wx_token'
const USER_KEY = 'ailove_wx_user'

let _reloginHandler = null

function getToken() {
  return wx.getStorageSync(TOKEN_KEY) || ''
}

function clearAuthStorage() {
  wx.removeStorageSync(TOKEN_KEY)
  wx.removeStorageSync(USER_KEY)
}

function clearAuthState() {
  clearAuthStorage()
  try {
    const app = getApp()
    if (app && app.globalData) {
      app.globalData.token = ''
      app.globalData.userInfo = null
    }
  } catch (_e) {
    // App 尚未初始化时忽略
  }
}

function registerUnauthorizedRelogin(handler) {
  _reloginHandler = typeof handler === 'function' ? handler : null
}

function trySilentRelogin() {
  if (typeof _reloginHandler !== 'function') {
    return Promise.resolve(false)
  }
  return Promise.resolve()
    .then(() => _reloginHandler())
    .then(() => Boolean(getToken()))
    .catch(() => false)
}

/**
 * 统一封装 wx.request，自动注入 Authorization 并解包后端统一结构 { code, message, data }
 * 若本地旧 Token 过期触发 401，将自动静默重登并无缝重试一次。
 */
function request(options) {
  const {
    url,
    method = 'GET',
    data = {},
    header = {},
    needAuth = true,
    timeout = 60000,
    _retried = false,
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
          clearAuthState()
          if (needAuth && Boolean(token) && !_retried) {
            trySilentRelogin().then((ok) => {
              if (ok) {
                request(Object.assign({}, options, { _retried: true }))
                  .then(resolve)
                  .catch(reject)
              } else {
                reject(new Error(body.message || '登录已过期，请重新登录'))
              }
            })
            return
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
  clearAuthState,
  registerUnauthorizedRelogin,
  trySilentRelogin,
  TOKEN_KEY,
  USER_KEY,
}
