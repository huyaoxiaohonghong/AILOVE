const {
  request,
  clearAuthState,
  registerUnauthorizedRelogin,
  TOKEN_KEY,
  USER_KEY,
} = require('./request')

let _inFlightLogin = null

function getToken() {
  return wx.getStorageSync(TOKEN_KEY) || ''
}

function getCachedUser() {
  return wx.getStorageSync(USER_KEY) || null
}

function saveSession(token, user) {
  wx.setStorageSync(TOKEN_KEY, token)
  wx.setStorageSync(USER_KEY, user)
  const app = getApp()
  if (app && app.globalData) {
    app.globalData.token = token
    app.globalData.userInfo = user
  }
}

function logout() {
  _inFlightLogin = null
  clearAuthState()
}

/**
 * 调用 wx.login 获取 code 并向 FastAPI 后端换取 JWT Token（静默登录自动并发去重）
 */
function wxLogin(extraProfile = {}) {
  const hasExtra = Boolean(extraProfile && (extraProfile.nickname || extraProfile.avatar_url))
  if (!hasExtra && _inFlightLogin) {
    return _inFlightLogin
  }

  const loginPromise = new Promise((resolve, reject) => {
    wx.login({
      success(loginRes) {
        if (!loginRes.code) {
          reject(new Error('wx.login 未返回 code'))
          return
        }
        request({
          url: '/miniapp/auth/wx-login',
          method: 'POST',
          needAuth: false,
          data: {
            code: loginRes.code,
            nickname: extraProfile.nickname || undefined,
            avatar_url: extraProfile.avatar_url || undefined,
          },
        })
          .then((res) => {
            saveSession(res.access_token, res.user)
            resolve(res)
          })
          .catch(reject)
      },
      fail(err) {
        reject(new Error(err.errMsg || '调用 wx.login 失败'))
      },
    })
  })

  if (!hasExtra) {
    _inFlightLogin = loginPromise
    loginPromise.then(
      () => {
        if (_inFlightLogin === loginPromise) _inFlightLogin = null
      },
      () => {
        if (_inFlightLogin === loginPromise) _inFlightLogin = null
      }
    )
  }

  return loginPromise
}

/**
 * 若本地无 token 则自动完成静默微信登录
 */
async function ensureLogin() {
  if (getToken()) {
    return getCachedUser()
  }
  const res = await wxLogin()
  return res.user
}

// 注册 401 令牌过期时的单飞静默重登处理器
registerUnauthorizedRelogin(() => wxLogin())

module.exports = {
  getToken,
  getCachedUser,
  saveSession,
  logout,
  wxLogin,
  ensureLogin,
}
