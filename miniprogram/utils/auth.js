const { request, TOKEN_KEY, USER_KEY } = require('./request')

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
  wx.removeStorageSync(TOKEN_KEY)
  wx.removeStorageSync(USER_KEY)
  const app = getApp()
  if (app && app.globalData) {
    app.globalData.token = ''
    app.globalData.userInfo = null
  }
}

/**
 * 调用 wx.login 获取 code 并向 FastAPI 后端换取 JWT Token
 */
function wxLogin(extraProfile = {}) {
  return new Promise((resolve, reject) => {
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

module.exports = {
  getToken,
  getCachedUser,
  saveSession,
  logout,
  wxLogin,
  ensureLogin,
}
