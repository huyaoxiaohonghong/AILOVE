const { request } = require('../utils/request')

function getHealth() {
  return request({
    url: '/health',
    method: 'GET',
    needAuth: false,
  })
}

function getUserProfile() {
  return request({
    url: '/miniapp/user/profile',
    method: 'GET',
  })
}

function sendAiChat(payload) {
  return request({
    url: '/ai/chat',
    method: 'POST',
    data: payload,
  })
}

function clearAiSession(sessionId) {
  return request({
    url: `/ai/sessions/${encodeURIComponent(sessionId)}`,
    method: 'DELETE',
  })
}

module.exports = {
  getHealth,
  getUserProfile,
  sendAiChat,
  clearAiSession,
}
