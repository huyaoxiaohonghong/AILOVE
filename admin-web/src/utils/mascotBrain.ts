export type MascotMood =
  | 'idle'
  | 'happy'
  | 'shy'
  | 'curious'
  | 'thinking'
  | 'comfort'
  | 'sleepy'
  | 'pout'
  | 'dizzy'
  | 'excited'

export type MascotGesture =
  | 'rub_head'
  | 'poke_cheek'
  | 'pull_ear'
  | 'pull_tail'
  | 'combo_dizzy'
  | 'long_hug'
  | 'drag_swing'
  | 'edge_peek'

export type MascotChoreoAction =
  | 'none'
  | 'ear_twitch'
  | 'tail_turbo'
  | 'blush'
  | 'hug'
  | 'nod'
  | 'sparkle'

export interface MascotEmoDirective {
  emo: MascotMood
  act: MascotChoreoAction
  dv: number
  da: number
}

export interface MascotToolDirective {
  type: 'open_reply_helper' | 'open_soften_draft' | 'propose_profile_update' | 'start_calm_breathing'
  label: string
  partner_message?: string
  scene?: string
  tone?: string
  draft_message?: string
  intensity?: 'mild' | 'medium' | 'heated'
  summary?: string
  patch?: {
    relationship_stage?: string
    partner_nickname?: string
    partner_traits?: string[]
    my_traits?: string[]
    relationship_goal?: string
    communication_taboos?: string
    background_notes?: string
  }
  seconds?: number
}

export interface PADVector {
  valence: number // [-1, 1]
  arousal: number // [0, 1]
  affinity: number // [0, 100]
}

export interface ModulatedMotionParams {
  tailFreqHz: number
  tailAmpDeg: number
  blushOpacity: number
  breathAmpPx: number
  breathPeriodSec: number
}

const VALID_MOODS = new Set<MascotMood>([
  'idle',
  'happy',
  'shy',
  'curious',
  'thinking',
  'comfort',
  'sleepy',
  'pout',
  'dizzy',
  'excited',
])

const VALID_ACTIONS = new Set<MascotChoreoAction>([
  'none',
  'ear_twitch',
  'tail_turbo',
  'blush',
  'hug',
  'nod',
  'sparkle',
])

export function clamp(val: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, val))
}

/**
 * 二阶弹簧阻尼谐振子：a = k * (target - x) - c * v, c = 2 * zeta * sqrt(k)
 * 使用半隐式欧拉步进，稳定且每帧开销 < 0.01ms。
 */
export class Spring1D {
  x: number
  v: number
  target: number
  k: number
  zeta: number

  constructor(initial = 0, stiffness = 140, dampingRatio = 0.52) {
    this.x = initial
    this.v = 0
    this.target = initial
    this.k = stiffness
    this.zeta = dampingRatio
  }

  impulse(deltaV: number) {
    this.v += deltaV
  }

  step(dtSec: number): number {
    const dt = clamp(dtSec, 0.001, 0.045)
    const c = 2 * this.zeta * Math.sqrt(this.k)
    const a = this.k * (this.target - this.x) - c * this.v
    this.v += a * dt
    this.x += this.v * dt
    return this.x
  }
}

/**
 * 实时眼动向量（双曲正切平滑限幅 + 轻微跳视避免恐怖谷效应）
 */
export function computeGazeOffset(
  pointerX: number,
  pointerY: number,
  eyeCenterX: number,
  eyeCenterY: number,
  maxRx = 3.6,
  maxRy = 2.6,
  scaleDist = 260,
): { gx: number; gy: number } {
  const dx = pointerX - eyeCenterX
  const dy = pointerY - eyeCenterY
  return {
    gx: maxRx * Math.tanh(dx / scaleDist),
    gy: maxRy * Math.tanh(dy / scaleDist),
  }
}

/**
 * 威布尔分布自然眨眼间隔采样（支持 18% 双连眨）
 */
export function sampleWeibullBlinkDelayMs(isSleepy = false): { delayMs: number; doubleBlink: boolean } {
  const u = Math.min(0.995, Math.max(0.01, Math.random()))
  const shapeK = 2.4
  const scaleLambda = isSleepy ? 2600 : 3900
  const raw = scaleLambda * Math.pow(-Math.log(1 - u), 1 / shapeK)
  return {
    delayMs: Math.round(clamp(raw, 1300, 6600)),
    doubleBlink: Math.random() < (isSleepy ? 0.28 : 0.18),
  }
}

/**
 * 昼夜节律基线
 */
export function getCircadianBaseline(hour = new Date().getHours()): {
  valence: number
  arousal: number
  phase: 'late_night' | 'morning' | 'noon' | 'daytime' | 'evening'
} {
  if (hour >= 23 || hour < 5) return { valence: 0.14, arousal: 0.14, phase: 'late_night' }
  if (hour >= 5 && hour < 10) return { valence: 0.3, arousal: 0.44, phase: 'morning' }
  if (hour >= 12 && hour < 14) return { valence: 0.24, arousal: 0.28, phase: 'noon' }
  if (hour >= 18 && hour < 23) return { valence: 0.26, arousal: 0.38, phase: 'evening' }
  return { valence: 0.24, arousal: 0.36, phase: 'daytime' }
}

/**
 * PAD 连续情感指数稳态衰减
 */
export function decayPAD(state: PADVector, elapsedSec: number, hour?: number): PADVector {
  const base = getCircadianBaseline(hour)
  const factor = Math.exp(-0.0022 * Math.max(0, elapsedSec))
  return {
    valence: clamp(base.valence + (state.valence - base.valence) * factor, -1, 1),
    arousal: clamp(base.arousal + (state.arousal - base.arousal) * factor, 0, 1),
    affinity: clamp(state.affinity, 0, 100),
  }
}

const MOOD_PROTOTYPES: Array<[MascotMood, number, number]> = [
  ['excited', 0.78, 0.85],
  ['happy', 0.65, 0.6],
  ['shy', 0.45, 0.46],
  ['curious', 0.18, 0.66],
  ['idle', 0.22, 0.36],
  ['sleepy', 0.1, 0.12],
  ['pout', -0.3, 0.56],
  ['comfort', -0.58, 0.28],
]

export function mapPADToMood(valence: number, arousal: number): MascotMood {
  let best: MascotMood = 'idle'
  let bestDist = Infinity
  for (const [m, pv, pa] of MOOD_PROTOTYPES) {
    const d = (valence - pv) ** 2 + (arousal - pa) ** 2
    if (d < bestDist) {
      bestDist = d
      best = m
    }
  }
  return best
}

/**
 * 将连续 PAD 情感坐标映射为连续可调的物理动效参数
 */
export function computeModulatedMotionParams(pad: PADVector, mood: MascotMood): ModulatedMotionParams {
  let arousalEff = pad.arousal
  if (mood === 'excited' || mood === 'happy') arousalEff = Math.max(arousalEff, 0.78)
  if (mood === 'sleepy') arousalEff = Math.min(arousalEff, 0.14)
  if (mood === 'dizzy') arousalEff = 0.92

  const tailFreqHz = 0.35 + 1.15 * arousalEff
  const tailAmpDeg = mood === 'comfort' ? 3.5 : 5 + 10.5 * arousalEff
  const blushBoost = mood === 'shy' ? 0.32 : mood === 'happy' ? 0.12 : 0
  const blushOpacity = clamp(
    0.42 + 0.38 * Math.max(0, pad.valence) + 0.002 * pad.affinity + blushBoost,
    0.32,
    0.96,
  )
  const breathAmpPx = 3.2 + 2.8 * (1 - arousalEff)
  const breathPeriodSec = 2.2 + 1.8 * (1 - arousalEff)
  return { tailFreqHz, tailAmpDeg, blushOpacity, breathAmpPx, breathPeriodSec }
}

/**
 * 归一化触控热区分类
 */
export type HitZone = 'ear' | 'head' | 'cheek' | 'tail' | 'body'

export function classifyHitZone(relX: number, relY: number): HitZone {
  const u = clamp(relX, 0, 1)
  const v = clamp(relY, 0, 1)
  if (v < 0.32 && (u < 0.33 || u > 0.67)) return 'ear'
  if (v < 0.38) return 'head'
  if (v >= 0.38 && v <= 0.58 && u >= 0.22 && u <= 0.78) return 'cheek'
  if (u < 0.36 && v > 0.52) return 'tail'
  return 'body'
}

export interface UtilityContext {
  idleSec: number
  drawerOpen: boolean
  minimized: boolean
  hour: number
  pad: PADVector
  routePath: string
}

export interface AutonomousDecision {
  actionId: string
  mood?: MascotMood
  choreoAction?: MascotChoreoAction
  bubble?: string
  durationMs?: number
}

interface CandidateSpec {
  id: string
  baseWeight: number
  cooldownSec: number
  isBubble: boolean
  evaluate: (ctx: UtilityContext) => { score: number; decision: AutonomousDecision } | null
}

/**
 * Utility AI 自主生命行为调度器 + 防打扰疲劳衰减曲线
 */
export class UtilityBehaviorScheduler {
  private lastFired = new Map<string, number>()
  private fatigue = 0
  private lastTickAt = Date.now()

  private candidates: CandidateSpec[] = [
    {
      id: 'late_night_sleepy',
      baseWeight: 1.35,
      cooldownSec: 180,
      isBubble: true,
      evaluate: (ctx) => {
        if (!(ctx.hour >= 23 || ctx.hour < 5) || ctx.idleSec < 18) return null
        return {
          score: 1.0,
          decision: {
            actionId: 'late_night_sleepy',
            mood: 'sleepy',
            bubble: '哈欠~ 夜深啦，眼睛累了就早点休息，明天我还在哦 🌙',
            durationMs: 4200,
          },
        }
      },
    },
    {
      id: 'morning_stretch',
      baseWeight: 1.15,
      cooldownSec: 600,
      isBubble: true,
      evaluate: (ctx) => {
        if (ctx.hour < 6 || ctx.hour >= 10 || ctx.idleSec < 12) return null
        return {
          score: 0.95,
          decision: {
            actionId: 'morning_stretch',
            mood: 'happy',
            choreoAction: 'sparkle',
            bubble: '早安呀~ 伸个懒腰，今天也要顺顺利利、甜甜的 ✨',
            durationMs: 4000,
          },
        }
      },
    },
    {
      id: 'ear_twitch_idle',
      baseWeight: 1.0,
      cooldownSec: 22,
      isBubble: false,
      evaluate: (ctx) => {
        if (ctx.idleSec < 10) return null
        return {
          score: 0.85,
          decision: {
            actionId: 'ear_twitch_idle',
            choreoAction: 'ear_twitch',
          },
        }
      },
    },
    {
      id: 'curious_look',
      baseWeight: 0.9,
      cooldownSec: 45,
      isBubble: false,
      evaluate: (ctx) => {
        if (ctx.idleSec < 22 || ctx.hour >= 23 || ctx.hour < 5) return null
        return {
          score: 0.8,
          decision: {
            actionId: 'curious_look',
            mood: 'curious',
            choreoAction: 'nod',
            durationMs: 2800,
          },
        }
      },
    },
    {
      id: 'edge_peek_wave',
      baseWeight: 0.95,
      cooldownSec: 240,
      isBubble: true,
      evaluate: (ctx) => {
        if (!ctx.minimized || ctx.idleSec < 40) return null
        return {
          score: 0.9,
          decision: {
            actionId: 'edge_peek_wave',
            mood: 'curious',
            bubble: '探头~ 有卡壳的聊天随时喊我出来支招呀',
            durationMs: 3600,
          },
        }
      },
    },
    {
      id: 'playground_nudge',
      baseWeight: 0.85,
      cooldownSec: 300,
      isBubble: true,
      evaluate: (ctx) => {
        if (ctx.minimized || ctx.idleSec < 50 || ctx.routePath !== '/ai-playground') return null
        return {
          score: 0.85,
          decision: {
            actionId: 'playground_nudge',
            mood: 'curious',
            choreoAction: 'ear_twitch',
            bubble: '偷偷告诉你：直接点我摸摸头，或者把聊天截图发过来都能帮你想回复~',
            durationMs: 4200,
          },
        }
      },
    },
  ]

  onBubbleDismissed() {
    this.fatigue = clamp(this.fatigue + 0.38, 0, 0.94)
  }

  onBubbleIgnored() {
    this.fatigue = clamp(this.fatigue + 0.18, 0, 0.94)
  }

  onUserEngaged() {
    this.fatigue = clamp(this.fatigue * 0.35, 0, 0.94)
  }

  tick(ctx: UtilityContext): AutonomousDecision | null {
    const now = Date.now()
    const dtMin = (now - this.lastTickAt) / 60000
    this.lastTickAt = now
    // 疲劳度随时间缓慢自然恢复
    this.fatigue = clamp(this.fatigue * Math.exp(-0.08 * Math.max(0, dtMin)), 0, 0.94)

    if (ctx.drawerOpen) return null

    let bestScore = 0.25
    let bestDecision: AutonomousDecision | null = null

    for (const spec of this.candidates) {
      const res = spec.evaluate(ctx)
      if (!res) continue
      const last = this.lastFired.get(spec.id) || 0
      const elapsedSec = (now - last) / 1000
      const cooldownFactor = last === 0 ? 1 : 1 - Math.exp(-elapsedSec / spec.cooldownSec)
      if (last > 0 && elapsedSec < spec.cooldownSec * 0.55) continue

      const fatigueFactor = spec.isBubble ? 1 - this.fatigue : 1
      const jitter = 0.88 + Math.random() * 0.24
      const utility = spec.baseWeight * res.score * cooldownFactor * fatigueFactor * jitter
      if (utility > bestScore) {
        bestScore = utility
        bestDecision = res.decision
      }
    }

    if (bestDecision) {
      this.lastFired.set(bestDecision.actionId, now)
    }
    return bestDecision
  }
}

/**
 * 双通道流式动作编排解析器
 * 实时剥离 [[emo:...]] 与 [[tool:{...}]]，驱动同步表情、工具卡片与音节口型脉冲。
 */
export class StreamingChoreographyParser {
  private buffer = ''
  private onEmo?: (dir: MascotEmoDirective) => void
  private onTool?: (tool: MascotToolDirective) => void
  private onText?: (chunk: string) => void
  private onSyllablePulse?: (openness: number) => void

  constructor(handlers: {
    onEmo?: (dir: MascotEmoDirective) => void
    onTool?: (tool: MascotToolDirective) => void
    onText?: (chunk: string) => void
    onSyllablePulse?: (openness: number) => void
  }) {
    this.onEmo = handlers.onEmo
    this.onTool = handlers.onTool
    this.onText = handlers.onText
    this.onSyllablePulse = handlers.onSyllablePulse
  }

  feed(chunk: string) {
    if (!chunk) return
    this.buffer += chunk
    this.drain(false)
  }

  flush() {
    this.drain(true)
  }

  private emitCleanText(text: string) {
    if (!text) return
    this.onText?.(text)
    if (this.onSyllablePulse) {
      const pause = /[，。！？、,.!?;:：\n…~]$/.test(text.trim())
      const hasWord = /[\u4e00-\u9fa5A-Za-z0-9]/.test(text)
      this.onSyllablePulse(pause ? 0.15 : hasWord ? 0.92 : 0.35)
    }
  }

  private handleTag(rawTag: string) {
    if (rawTag.startsWith('emo:')) {
      const body = rawTag.slice(4)
      const fields = new Map<string, string>()
      for (const seg of body.split('|')) {
        const idx = seg.indexOf(':')
        if (idx > 0) {
          fields.set(seg.slice(0, idx).trim().toLowerCase(), seg.slice(idx + 1).trim())
        }
      }
      const rawEmo = (fields.get('emo') || body.split('|')[0] || 'idle').trim().toLowerCase() as MascotMood
      const rawAct = (fields.get('act') || 'none').trim().toLowerCase() as MascotChoreoAction
      const dv = clamp(Number(fields.get('dv') ?? 0) || 0, -0.5, 0.5)
      const da = clamp(Number(fields.get('da') ?? 0) || 0, -0.5, 0.5)
      this.onEmo?.({
        emo: VALID_MOODS.has(rawEmo) ? rawEmo : 'idle',
        act: VALID_ACTIONS.has(rawAct) ? rawAct : 'none',
        dv,
        da,
      })
      return
    }
    if (rawTag.startsWith('tool:')) {
      const jsonStr = rawTag.slice(5).trim()
      try {
        const parsed = JSON.parse(jsonStr) as MascotToolDirective
        if (parsed && parsed.type && parsed.label) {
          this.onTool?.(parsed)
        }
      } catch {
        // 忽略非法 JSON 标签
      }
    }
  }

  private drain(isFinal: boolean) {
    while (this.buffer.length > 0) {
      const openIdx = this.buffer.indexOf('[[')
      if (openIdx === -1) {
        if (!isFinal && this.buffer.endsWith('[')) {
          const safe = this.buffer.slice(0, -1)
          if (safe) this.emitCleanText(safe)
          this.buffer = '['
          return
        }
        this.emitCleanText(this.buffer)
        this.buffer = ''
        return
      }

      if (openIdx > 0) {
        this.emitCleanText(this.buffer.slice(0, openIdx))
        this.buffer = this.buffer.slice(openIdx)
      }

      const closeIdx = this.buffer.indexOf(']]', 2)
      if (closeIdx === -1) {
        // 避免超长未闭合括号阻塞流
        if (isFinal || this.buffer.length > 900) {
          this.emitCleanText(this.buffer)
          this.buffer = ''
        }
        return
      }

      const inner = this.buffer.slice(2, closeIdx).trim()
      this.buffer = this.buffer.slice(closeIdx + 2)
      if (inner.startsWith('emo:') || inner.startsWith('tool:')) {
        // 吃掉紧随标签的单个换行，避免正文开头多出空行
        if (this.buffer.startsWith('\n')) {
          this.buffer = this.buffer.slice(1)
        }
        this.handleTag(inner)
      } else {
        this.emitCleanText(`[[${inner}]]`)
      }
    }
  }
}

const HEATED_RE = /(算了|随便你|受够了|别联系|懒得说|分手吧|烦死了|你从来都不|滚吧|没意思了)/

/**
 * 实时草稿情绪火药味 / 犹豫信号分析
 */
export function analyzeDraftSignal(text: string): 'heated' | null {
  const clean = (text || '').trim()
  if (clean.length < 4) return null
  if (HEATED_RE.test(clean)) return 'heated'
  return null
}

export const MOOD_LABELS: Record<MascotMood, string> = {
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
