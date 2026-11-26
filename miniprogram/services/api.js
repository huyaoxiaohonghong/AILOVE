const { request } = require('../utils/request')
const { streamSseRequest } = require('../utils/stream')

function getHealth() {
  return request({ url: '/health', method: 'GET', needAuth: false })
}

function getPublicConfig() {
  return request({ url: '/system/public-config', method: 'GET', needAuth: false })
}

// --- 小程序用户资料 ---
function getUserProfile() {
  return request({ url: '/miniapp/user/profile', method: 'GET' })
}

function updateUserProfile(payload) {
  return request({ url: '/miniapp/user/profile', method: 'PATCH', data: payload })
}

function verifyInviteCode(inviteCode) {
  return request({
    url: '/miniapp/user/verify-invite',
    method: 'POST',
    data: { invite_code: inviteCode },
  })
}

// --- 恋爱智能体与配额 ---
function getPersonas(category) {
  const qs = category && category !== 'all' ? `?category=${encodeURIComponent(category)}` : ''
  return request({ url: `/ai/personas${qs}`, method: 'GET' })
}

function getKbSkills() {
  return request({ url: '/kb/skills', method: 'GET' })
}

function getMyQuota() {
  return request({ url: '/ai/quota', method: 'GET' })
}

// --- 持久化多会话与置顶 ---
function getConversations() {
  return request({ url: '/ai/conversations', method: 'GET' })
}

function getConversationMessages(sessionId) {
  return request({
    url: `/ai/conversations/${encodeURIComponent(sessionId)}/messages`,
    method: 'GET',
  })
}

function updateConversation(sessionId, payload) {
  return request({
    url: `/ai/conversations/${encodeURIComponent(sessionId)}`,
    method: 'PATCH',
    data: payload,
  })
}

function deleteConversation(sessionId) {
  return request({
    url: `/ai/conversations/${encodeURIComponent(sessionId)}`,
    method: 'DELETE',
  })
}

// --- 个人情感背景记忆卡 ---
function getLoveProfile() {
  return request({ url: '/ai/love-profile', method: 'GET' })
}

function saveLoveProfile(payload) {
  return request({ url: '/ai/love-profile', method: 'PUT', data: payload })
}

function clearLoveProfile() {
  return request({ url: '/ai/love-profile', method: 'DELETE' })
}

// --- 帮我回消息 ---
function getReplyHelperPresets() {
  return request({ url: '/ai/reply-helper/presets', method: 'GET' })
}

function sendReplyHelper(payload) {
  return request({ url: '/ai/reply-helper', method: 'POST', data: payload, timeout: 90000 })
}

function streamReplyHelper(payload, callbacks) {
  return streamSseRequest(
    Object.assign({ url: '/ai/reply-helper/stream', data: payload }, callbacks)
  )
}

// --- 先别发！情绪降温与话术柔化 ---
function getSoftenPresets() {
  return request({ url: '/ai/soften-draft/presets', method: 'GET' })
}

function streamSoftenDraft(payload, callbacks) {
  return streamSseRequest(
    Object.assign({ url: '/ai/soften-draft/stream', data: payload }, callbacks)
  )
}

// --- 高情商话术收藏夹 ---
function getFavorites(category) {
  const qs = category && category !== 'all' ? `?category=${encodeURIComponent(category)}` : ''
  return request({ url: `/ai/favorites${qs}`, method: 'GET' })
}

function saveFavorite(payload) {
  return request({ url: '/ai/favorites', method: 'POST', data: payload })
}

function deleteFavorite(favoriteId) {
  return request({
    url: `/ai/favorites/${encodeURIComponent(favoriteId)}`,
    method: 'DELETE',
  })
}

// --- 个人数据导出与销毁（数据主权） ---
function exportMyJournalJson() {
  return request({ url: '/ai/my-data/export?format=json', method: 'GET', timeout: 60000 })
}

function purgeMyData() {
  return request({
    url: '/ai/my-data?include_love_profile=true&include_favorites=true',
    method: 'DELETE',
  })
}

// --- AI 对话（同步 + 流式） ---
function sendAiChat(payload) {
  return request({ url: '/ai/chat', method: 'POST', data: payload, timeout: 90000 })
}

function streamAiChat(payload, callbacks) {
  return streamSseRequest(
    Object.assign({ url: '/ai/chat/stream', data: payload }, callbacks)
  )
}

function clearAiSession(sessionId) {
  return request({
    url: `/ai/sessions/${encodeURIComponent(sessionId)}`,
    method: 'DELETE',
  })
}

module.exports = {
  getHealth,
  getPublicConfig,
  getUserProfile,
  updateUserProfile,
  verifyInviteCode,
  getPersonas,
  getKbSkills,
  getMyQuota,
  getConversations,
  getConversationMessages,
  updateConversation,
  deleteConversation,
  getLoveProfile,
  saveLoveProfile,
  clearLoveProfile,
  getReplyHelperPresets,
  sendReplyHelper,
  streamReplyHelper,
  getSoftenPresets,
  streamSoftenDraft,
  getFavorites,
  saveFavorite,
  deleteFavorite,
  exportMyJournalJson,
  purgeMyData,
  sendAiChat,
  streamAiChat,
  clearAiSession,
}
