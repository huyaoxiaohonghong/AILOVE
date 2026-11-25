const api = require('../../services/api')
const auth = require('../../utils/auth')

const CATEGORIES = [
  { key: 'all', label: '全部' },
  { key: 'reply_helper', label: '回消息' },
  { key: 'soften', label: '先别发' },
  { key: 'chat', label: '对话收藏' },
  { key: 'custom', label: '自定义' },
]

Page({
  data: {
    loading: true,
    categories: CATEGORIES,
    activeCategory: 'all',
    items: [],
    newContent: '',
    newNote: '',
    saving: false,
  },

  onLoad() {
    this.loadList()
  },

  onPullDownRefresh() {
    this.loadList().finally(() => {
      wx.stopPullDownRefresh()
    })
  },

  async loadList() {
    this.setData({ loading: true })
    try {
      await auth.ensureLogin()
      const res = await api.getFavorites(this.data.activeCategory)
      this.setData({ items: (res && res.items) || [] })
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '加载收藏失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  onSelectCategory(e) {
    const key = e.currentTarget.dataset.key || 'all'
    if (key === this.data.activeCategory) return
    this.setData({ activeCategory: key })
    this.loadList()
  },

  onContentInput(e) {
    this.setData({ newContent: e.detail.value })
  },

  onNoteInput(e) {
    this.setData({ newNote: e.detail.value })
  },

  async handleAddCustom() {
    const content = (this.data.newContent || '').trim()
    if (!content) {
      wx.showToast({ title: '请输入想要保存的高情商话术', icon: 'none' })
      return
    }
    if (this.data.saving) return
    this.setData({ saving: true })
    try {
      const res = await api.saveFavorite({
        content,
        category: 'custom',
        scene_label: '随手备忘',
        note: (this.data.newNote || '').trim(),
      })
      this.setData({ newContent: '', newNote: '' })
      wx.showToast({
        title: res && res.deduplicated ? '已在收藏夹中' : '已加入话术库',
        icon: 'success',
      })
      await this.loadList()
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
    } finally {
      this.setData({ saving: false })
    }
  },

  onCopyItem(e) {
    const txt = e.currentTarget.dataset.content || ''
    if (!txt) return
    wx.setClipboardData({
      data: txt,
      success() {
        wx.showToast({ title: '已复制到剪贴板', icon: 'success' })
      },
    })
  },

  onDeleteItem(e) {
    const id = Number(e.currentTarget.dataset.id)
    if (!id) return
    wx.showModal({
      title: '移出收藏夹',
      content: '确认删除这条已收藏的话术？',
      confirmColor: '#c83553',
      success: async (res) => {
        if (!res.confirm) return
        try {
          await api.deleteFavorite(id)
          wx.showToast({ title: '已删除', icon: 'none' })
          await this.loadList()
        } catch (err) {
          wx.showToast({ title: (err && err.message) || '删除失败', icon: 'none' })
        }
      },
    })
  },
})
