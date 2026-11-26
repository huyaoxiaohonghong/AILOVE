/**
 * 恋恋 2.0 微信小程序端轻量化算法核心（零依赖）
 * - PAD 连续情感动力学 + 昼夜节律稳态衰减
 * - 威布尔分布自然眨眼（含双连眨）
 * - 部位热区分类（摸头 / 戳脸 / 揪耳 / 拽尾巴 / 抱抱）
 * - Utility AI 自主生命行为调度器 + 防打扰疲劳曲线
 * - 双通道流式动作编排解析器 [[emo:...]] / [[tool:...]]
 */

const VALID_MOODS = {
  idle: true,
  happy: true,
  shy: true,
  curious: true,
  thinking: true,
  comfort: true,
  sleepy: true,
  pout: true,
  dizzy: true,
  excited: true,
}

const VALID_ACTIONS = {
  none: true,
  ear_twitch: true,
  tail_turbo: true,
  blush: true,
  hug: true,
  nod: true,
  sparkle: true,
}

const MOOD_LABELS = {
  idle: '在线陪伴中',
  happy: '开心转圈圈 ✨',
  shy: '耳朵红红的 💗',
  curious: '竖耳好奇中',
  thinking: '歪头思索中...',
  comfort: '递热可可抱抱',
  sleepy: '揉眼打哈欠 🌙',
  pout: '鼓嘴小脾气',
  dizzy: '转圈圈晕啦 @_@',
  excited: '星星眼击掌 ⭐',
}

// 9 张可用立绘映射（excited 复用 happy + 星星叠加特效，pout 复用 shy + 鼓嘴气泡）
const MOOD_SPRITE_MAP = {
  idle: 'idle',
  happy: 'happy',
  shy: 'shy',
  curious: 'curious',
  thinking: 'thinking',
  comfort: 'comfort',
  sleepy: 'sleepy',
  pout: 'shy',
  dizzy: 'dizzy',
  excited: 'happy',
}

const MOOD_PROTOTYPES = [
  ['excited', 0.78, 0.85],
  ['happy', 0.65, 0.6],
  ['shy', 0.45, 0.46],
  ['curious', 0.18, 0.66],
  ['idle', 0.22, 0.36],
  ['sleepy', 0.1, 0.12],
  ['pout', -0.3, 0.56],
  ['comfort', -0.58, 0.28],
]

function clamp(val, min, max) {
  return Math.max(min, Math.min(max, val))
}

function getCircadianBaseline(hour) {
  const h = typeof hour === 'number' ? hour : new Date().getHours()
  if (h >= 23 || h < 5) return { valence: 0.14, arousal: 0.14, phase: 'late_night' }
  if (h >= 5 && h < 10) return { valence: 0.3, arousal: 0.44, phase: 'morning' }
  if (h >= 12 && h < 14) return { valence: 0.24, arousal: 0.28, phase: 'noon' }
  if (h >= 18 && h < 23) return { valence: 0.26, arousal: 0.38, phase: 'evening' }
  return { valence: 0.24, arousal: 0.36, phase: 'daytime' }
}

function decayPAD(pad, elapsedSec, hour) {
  const base = getCircadianBaseline(hour)
  const factor = Math.exp(-0.0022 * Math.max(0, elapsedSec || 0))
  return {
    valence: clamp(base.valence + ((pad.valence || 0.25) - base.valence) * factor, -1, 1),
    arousal: clamp(base.arousal + ((pad.arousal || 0.35) - base.arousal) * factor, 0, 1),
    affinity: clamp(pad.affinity || 12, 0, 100),
  }
}

function mapPADToMood(valence, arousal) {
  let best = 'idle'
  let bestDist = 999
  for (let i = 0; i < MOOD_PROTOTYPES.length; i += 1) {
    const item = MOOD_PROTOTYPES[i]
    const d = (valence - item[1]) * (valence - item[1]) + (arousal - item[2]) * (arousal - item[2])
    if (d < bestDist) {
      bestDist = d
      best = item[0]
    }
  }
  return best
}

function sampleWeibullBlinkDelayMs(isSleepy) {
  const u = Math.min(0.995, Math.max(0.01, Math.random()))
  const shapeK = 2.4
  const scaleLambda = isSleepy ? 2600 : 3900
  const raw = scaleLambda * Math.pow(-Math.log(1 - u), 1 / shapeK)
  return {
    delayMs: Math.round(clamp(raw, 1300, 6500)),
    doubleBlink: Math.random() < (isSleepy ? 0.28 : 0.18),
  }
}

function classifyHitZone(relX, relY) {
  const u = clamp(relX, 0, 1)
  const v = clamp(relY, 0, 1)
  if (v < 0.34 && (u < 0.34 || u > 0.66)) return 'ear'
  if (v < 0.38) return 'head'
  if (v >= 0.38 && v <= 0.6 && u >= 0.22 && u <= 0.78) return 'cheek'
  if (u < 0.38 && v > 0.54) return 'tail'
  return 'body'
}

function triggerHaptic(kind) {
  try {
    if (!wx || typeof wx.vibrateShort !== 'function') return
    if (kind === 'heartbeat') {
      wx.vibrateShort({ type: 'light' })
      setTimeout(() => {
        try {
          wx.vibrateShort({ type: 'medium' })
        } catch (_e) {}
      }, 150)
      return
    }
    wx.vibrateShort({ type: kind === 'medium' ? 'medium' : 'light' })
  } catch (_e) {
    // 忽略部分机型不支持震动
  }
}

class UtilityBehaviorScheduler {
  constructor() {
    this.lastFired = {}
    this.fatigue = 0
    this.lastTickAt = Date.now()
  }

  onBubbleDismissed() {
    this.fatigue = clamp(this.fatigue + 0.38, 0, 0.94)
  }

  onUserEngaged() {
    this.fatigue = clamp(this.fatigue * 0.35, 0, 0.94)
  }

  tick(ctx) {
    const now = Date.now()
    const dtMin = (now - this.lastTickAt) / 60000
    this.lastTickAt = now
    this.fatigue = clamp(this.fatigue * Math.exp(-0.08 * Math.max(0, dtMin)), 0, 0.94)
    if (ctx.drawerOpen) return null

    const hour = typeof ctx.hour === 'number' ? ctx.hour : new Date().getHours()
    const candidates = []

    if ((hour >= 23 || hour < 5) && ctx.idleSec >= 14) {
      candidates.push({
        id: 'late_night_sleepy',
        baseWeight: 1.35,
        cooldownSec: 180,
        isBubble: true,
        decision: {
          actionId: 'late_night_sleepy',
          mood: 'sleepy',
          bubble: '哈欠~ 夜深啦，眼睛累了就早点睡，明天我还在哦 🌙',
          durationMs: 4000,
        },
      })
    }
    if (hour >= 6 && hour < 10 && ctx.idleSec >= 10) {
      candidates.push({
        id: 'morning_stretch',
        baseWeight: 1.15,
        cooldownSec: 600,
        isBubble: true,
        decision: {
          actionId: 'morning_stretch',
          mood: 'happy',
          bubble: '早安呀~ 摸摸头打个气，今天也要甜甜的 ✨',
          durationMs: 3800,
        },
      })
    }
    if (ctx.idleSec >= 18 && hour >= 5 && hour < 23) {
      candidates.push({
        id: 'curious_tilt',
        baseWeight: 0.95,
        cooldownSec: 36,
        isBubble: false,
        decision: {
          actionId: 'curious_tilt',
          mood: 'curious',
          durationMs: 2600,
        },
      })
    }
    if (ctx.minimized && ctx.idleSec >= 35) {
      candidates.push({
        id: 'edge_peek_wave',
        baseWeight: 0.92,
        cooldownSec: 220,
        isBubble: true,
        decision: {
          actionId: 'edge_peek_wave',
          mood: 'curious',
          bubble: '探头~ 有拿不准的消息随时喊我呀',
          durationMs: 3400,
        },
      })
    }

    let bestScore = 0.25
    let bestDecision = null
    for (let i = 0; i < candidates.length; i += 1) {
      const c = candidates[i]
      const last = this.lastFired[c.id] || 0
      const elapsedSec = (now - last) / 1000
      if (last > 0 && elapsedSec < c.cooldownSec * 0.55) continue
      const coolFactor = last === 0 ? 1 : 1 - Math.exp(-elapsedSec / c.cooldownSec)
      const fatigueFactor = c.isBubble ? 1 - this.fatigue : 1
      const utility = c.baseWeight * coolFactor * fatigueFactor * (0.88 + Math.random() * 0.24)
      if (utility > bestScore) {
        bestScore = utility
        bestDecision = c.decision
      }
    }
    if (bestDecision) {
      this.lastFired[bestDecision.actionId] = now
    }
    return bestDecision
  }
}

class StreamingChoreographyParser {
  constructor(handlers) {
    this.buffer = ''
    this.onEmo = handlers.onEmo
    this.onTool = handlers.onTool
    this.onText = handlers.onText
  }

  feed(chunk) {
    if (!chunk) return
    this.buffer += chunk
    this._drain(false)
  }

  flush() {
    this._drain(true)
  }

  _handleTag(rawTag) {
    if (rawTag.indexOf('emo:') === 0) {
      const body = rawTag.slice(4)
      const fields = {}
      const parts = body.split('|')
      for (let i = 0; i < parts.length; i += 1) {
        const seg = parts[i]
        const idx = seg.indexOf(':')
        if (idx > 0) {
          fields[seg.slice(0, idx).trim().toLowerCase()] = seg.slice(idx + 1).trim()
        }
      }
      const rawEmo = (fields.emo || parts[0] || 'idle').trim().toLowerCase()
      const rawAct = (fields.act || 'none').trim().toLowerCase()
      const dv = clamp(Number(fields.dv || 0) || 0, -0.5, 0.5)
      const da = clamp(Number(fields.da || 0) || 0, -0.5, 0.5)
      if (typeof this.onEmo === 'function') {
        this.onEmo({
          emo: VALID_MOODS[rawEmo] ? rawEmo : 'idle',
          act: VALID_ACTIONS[rawAct] ? rawAct : 'none',
          dv,
          da,
        })
      }
      return
    }
    if (rawTag.indexOf('tool:') === 0) {
      try {
        const parsed = JSON.parse(rawTag.slice(5).trim())
        if (parsed && parsed.type && parsed.label && typeof this.onTool === 'function') {
          this.onTool(parsed)
        }
      } catch (_e) {
        // 忽略无效 JSON
      }
    }
  }

  _drain(isFinal) {
    while (this.buffer.length > 0) {
      const openIdx = this.buffer.indexOf('[[')
      if (openIdx === -1) {
        if (!isFinal && this.buffer.endsWith('[')) {
          const safe = this.buffer.slice(0, -1)
          if (safe && typeof this.onText === 'function') this.onText(safe)
          this.buffer = '['
          return
        }
        if (typeof this.onText === 'function') this.onText(this.buffer)
        this.buffer = ''
        return
      }
      if (openIdx > 0) {
        if (typeof this.onText === 'function') this.onText(this.buffer.slice(0, openIdx))
        this.buffer = this.buffer.slice(openIdx)
      }
      const closeIdx = this.buffer.indexOf(']]', 2)
      if (closeIdx === -1) {
        if (isFinal || this.buffer.length > 900) {
          if (typeof this.onText === 'function') this.onText(this.buffer)
          this.buffer = ''
        }
        return
      }
      const inner = this.buffer.slice(2, closeIdx).trim()
      this.buffer = this.buffer.slice(closeIdx + 2)
      if (inner.indexOf('emo:') === 0 || inner.indexOf('tool:') === 0) {
        if (this.buffer.indexOf('\n') === 0) {
          this.buffer = this.buffer.slice(1)
        }
        this._handleTag(inner)
      } else if (typeof this.onText === 'function') {
        this.onText(`[[${inner}]]`)
      }
    }
  }
}

module.exports = {
  MOOD_LABELS,
  MOOD_SPRITE_MAP,
  clamp,
  getCircadianBaseline,
  decayPAD,
  mapPADToMood,
  sampleWeibullBlinkDelayMs,
  classifyHitZone,
  triggerHaptic,
  UtilityBehaviorScheduler,
  StreamingChoreographyParser,
}
