const api = require('../../services/api')
const auth = require('../../utils/auth')

Page({
  data: {
    sessionId: '',
    inputValue: '',
    sending: false,
    scrollToId: '',
    messages: [
      {
        id: 1,
        role: 'assistant',
        content: '你好！我是 AILOVE 智能助手，请问有什么可以帮你？',
      },
    ],
  },

  onInputChange(e) {
    this.setData({ inputValue: e.detail.value })
  },

  async handleSend() {
    const content = (this.data.inputValue || '').trim()
    if (!content || this.data.sending) return

    const userMsg = { id: Date.now(), role: 'user', content }
    const nextList = this.data.messages.concat(userMsg)
    this.setData({
      messages: nextList,
      inputValue: '',
      sending: true,
      scrollToId: 'msg-loading',
    })

    try {
      await auth.ensureLogin()
      const res = await api.sendAiChat({
        message: content,
        session_id: this.data.sessionId || undefined,
      })

      const aiMsg = { id: Date.now() + 1, role: 'assistant', content: res.reply }
      this.setData({
        sessionId: res.session_id,
        messages: this.data.messages.concat(aiMsg),
        scrollToId: `msg-${aiMsg.id}`,
      })
    } catch (err) {
      const errMsg = {
        id: Date.now() + 2,
        role: 'assistant',
        content: `发送失败：${err.message || '请检查后端服务是否启动'}`,
      }
      this.setData({
        messages: this.data.messages.concat(errMsg),
        scrollToId: `msg-${errMsg.id}`,
      })
    } finally {
      this.setData({ sending: false })
    }
  },

  async handleClearSession() {
    if (this.data.sessionId) {
      try {
        await api.clearAiSession(this.data.sessionId)
      } catch (_e) {
        // 忽略远端清理失败
      }
    }
    this.setData({
      sessionId: '',
      messages: [
        {
          id: Date.now(),
          role: 'assistant',
          content: '会话已清空，我们可以重新开始聊天。',
        },
      ],
    })
  },
})
