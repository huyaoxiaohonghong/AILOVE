const api = require('../../services/api')
const auth = require('../../utils/auth')

const DEFAULT_STAGES = [
  { code: 'single_crush', label: '暗恋观察期', emoji: '🌱' },
  { code: 'ambiguous', label: '暧昧升温期', emoji: '✨' },
  { code: 'in_love', label: '热恋甜蜜期', emoji: '💞' },
  { code: 'long_distance', label: '异地相处期', emoji: '🚄' },
  { code: 'cold_war', label: '争吵冷战修复', emoji: '🧊' },
  { code: 'breakup_healing', label: '失恋疗愈期', emoji: '🌙' },
  { code: 'married', label: '长期稳定/伴侣', emoji: '🏡' },
]

const DEFAULT_PARTNER_TRAITS = [
  '慢热型',
  '回避型依恋',
  '嘴硬心软',
  '工作忙回复慢',
  '细节控',
  '情绪敏感',
  '直球理性',
  '爱吃醋',
]

const DEFAULT_MY_TRAITS = [
  '容易内耗',
  '焦虑型依恋',
  '直球真诚',
  '不善表达',
  '容易心软',
  '注重仪式感',
]

Page({
  data: {
    loading: true,
    saving: false,
    stages: DEFAULT_STAGES,
    partnerTraitPresets: DEFAULT_PARTNER_TRAITS,
    myTraitPresets: DEFAULT_MY_TRAITS,
    relationshipStage: '',
    partnerNickname: '',
    partnerTraits: [],
    partnerTraitMap: {},
    myTraits: [],
    myTraitMap: {},
    customTraitInput: '',
    relationshipGoal: '',
    communicationTaboos: '',
    backgroundNotes: '',
    autoInject: true,
  },

  onLoad() {
    this.loadProfile()
  },

  toTagMap(list) {
    const map = {}
    ;(list || []).forEach((t) => {
      map[t] = true
    })
    return map
  },

  async loadProfile() {
    this.setData({ loading: true })
    try {
      await auth.ensureLogin()
      const res = await api.getLoveProfile()
      const p = (res && res.profile) || {}
      const presets = (res && res.presets) || {}
      const pTraits = p.partner_traits || []
      const mTraits = p.my_traits || []

      this.setData({
        stages: (presets.stages && presets.stages.length) ? presets.stages : DEFAULT_STAGES,
        partnerTraitPresets:
          (presets.partner_trait_presets && presets.partner_trait_presets.length)
            ? presets.partner_trait_presets
            : DEFAULT_PARTNER_TRAITS,
        myTraitPresets:
          (presets.my_trait_presets && presets.my_trait_presets.length)
            ? presets.my_trait_presets
            : DEFAULT_MY_TRAITS,
        relationshipStage: p.relationship_stage || '',
        partnerNickname: p.partner_nickname || '',
        partnerTraits: pTraits,
        partnerTraitMap: this.toTagMap(pTraits),
        myTraits: mTraits,
        myTraitMap: this.toTagMap(mTraits),
        relationshipGoal: p.relationship_goal || '',
        communicationTaboos: p.communication_taboos || '',
        backgroundNotes: p.background_notes || '',
        autoInject: p.auto_inject !== false,
      })
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  onToggleAutoInject(e) {
    this.setData({ autoInject: Boolean(e.detail.value) })
  },

  onSelectStage(e) {
    const code = e.currentTarget.dataset.code
    this.setData({
      relationshipStage: this.data.relationshipStage === code ? '' : code,
    })
  },

  onTogglePartnerTrait(e) {
    const tag = e.currentTarget.dataset.tag
    const list = this.data.partnerTraits.slice()
    const idx = list.indexOf(tag)
    if (idx >= 0) {
      list.splice(idx, 1)
    } else {
      if (list.length >= 8) {
        wx.showToast({ title: '最多选择 8 个标签', icon: 'none' })
        return
      }
      list.push(tag)
    }
    this.setData({ partnerTraits: list, partnerTraitMap: this.toTagMap(list) })
  },

  onToggleMyTrait(e) {
    const tag = e.currentTarget.dataset.tag
    const list = this.data.myTraits.slice()
    const idx = list.indexOf(tag)
    if (idx >= 0) {
      list.splice(idx, 1)
    } else {
      if (list.length >= 8) {
        wx.showToast({ title: '最多选择 8 个标签', icon: 'none' })
        return
      }
      list.push(tag)
    }
    this.setData({ myTraits: list, myTraitMap: this.toTagMap(list) })
  },

  onCustomTraitInput(e) {
    this.setData({ customTraitInput: e.detail.value })
  },

  onAddCustomTrait() {
    const val = (this.data.customTraitInput || '').trim().slice(0, 24)
    if (!val) return
    const list = this.data.partnerTraits.slice()
    if (list.indexOf(val) >= 0) {
      this.setData({ customTraitInput: '' })
      return
    }
    if (list.length >= 8) {
      wx.showToast({ title: '最多添加 8 个标签', icon: 'none' })
      return
    }
    list.push(val)
    this.setData({
      partnerTraits: list,
      partnerTraitMap: this.toTagMap(list),
      customTraitInput: '',
    })
  },

  onFieldInput(e) {
    const field = e.currentTarget.dataset.field
    if (field) {
      this.setData({ [field]: e.detail.value })
    }
  },

  async handleSave() {
    if (this.data.saving) return
    this.setData({ saving: true })
    try {
      await api.saveLoveProfile({
        relationship_stage: this.data.relationshipStage,
        partner_nickname: (this.data.partnerNickname || '').trim(),
        partner_traits: this.data.partnerTraits,
        my_traits: this.data.myTraits,
        relationship_goal: (this.data.relationshipGoal || '').trim(),
        communication_taboos: (this.data.communicationTaboos || '').trim(),
        background_notes: (this.data.backgroundNotes || '').trim(),
        auto_inject: this.data.autoInject,
      })
      wx.showToast({ title: '情感档案已生效', icon: 'success' })
      setTimeout(() => {
        wx.navigateBack({ fail: () => {} })
      }, 650)
    } catch (err) {
      wx.showToast({ title: (err && err.message) || '保存失败', icon: 'none' })
    } finally {
      this.setData({ saving: false })
    }
  },

  handleClear() {
    wx.showModal({
      title: '清空情感档案',
      content: '确认清空当前情感背景记忆卡？清空后可随时重新填写。',
      confirmColor: '#c83553',
      success: async (res) => {
        if (!res.confirm) return
        try {
          await api.clearLoveProfile()
          this.setData({
            relationshipStage: '',
            partnerNickname: '',
            partnerTraits: [],
            partnerTraitMap: {},
            myTraits: [],
            myTraitMap: {},
            relationshipGoal: '',
            communicationTaboos: '',
            backgroundNotes: '',
            autoInject: true,
          })
          wx.showToast({ title: '已清空档案', icon: 'none' })
        } catch (err) {
          wx.showToast({ title: (err && err.message) || '清空失败', icon: 'none' })
        }
      },
    })
  },
})
