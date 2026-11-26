<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import {
  clamp,
  sampleWeibullBlinkDelayMs,
  Spring1D,
  type MascotChoreoAction,
  type MascotMood,
} from '@/utils/mascotBrain'

const props = withDefaults(
  defineProps<{
    mood?: MascotMood
    speaking?: boolean
    mouthOpenness?: number
    size?: number
    bouncing?: boolean
    gazeX?: number
    gazeY?: number
    dragTiltDeg?: number
    blushOpacity?: number
    tailFreqHz?: number
    tailAmpDeg?: number
    breathAmpPx?: number
    actionPulse?: MascotChoreoAction
    actionSeq?: number
    interactive?: boolean
  }>(),
  {
    mood: 'idle',
    speaking: false,
    mouthOpenness: 0,
    size: 112,
    bouncing: false,
    gazeX: 0,
    gazeY: 0,
    dragTiltDeg: 0,
    blushOpacity: 0.68,
    tailFreqHz: 0.72,
    tailAmpDeg: 9,
    breathAmpPx: 4.2,
    actionPulse: 'none',
    actionSeq: 0,
    interactive: true,
  },
)

const uid = useId()
const defId = (name: string) => `${name}-${uid}`
const urlRef = (name: string) => `url(#${name}-${uid})`

// Natural Weibull blink + double-blink
const isBlinking = ref(false)
let blinkTimer: number | null = null
let blinkEndTimer: number | null = null
let doubleBlinkTimer: number | null = null

// Procedural 60fps Second-Order Spring-Damper Physics
const headAngle = ref(0)
const earLeftAngle = ref(0)
const earRightAngle = ref(0)
const tailAngle = ref(0)
const bodyFloatY = ref(0)
const bodyScaleX = ref(1)
const bodyScaleY = ref(1)
const eyeOffsetX = ref(0)
const eyeOffsetY = ref(0)
const mouthRy = ref(0.5)
const dizzySpin = ref(0)

const headSpring = new Spring1D(0, 130, 0.5)
const earLSpring = new Spring1D(0, 195, 0.42)
const earRSpring = new Spring1D(0, 195, 0.42)
const tailSpring = new Spring1D(0, 74, 0.58)
const scaleXSpring = new Spring1D(1, 210, 0.44)
const scaleYSpring = new Spring1D(1, 210, 0.44)
const gazeXSpring = new Spring1D(0, 160, 0.78)
const gazeYSpring = new Spring1D(0, 160, 0.78)
const mouthSpring = new Spring1D(0.5, 240, 0.72)

let rafId: number | null = null
let prevTimeMs = 0
let phaseClock = 0
let microSaccadeX = 0
let microSaccadeY = 0
let nextSaccadeAt = 0

function scheduleNextBlink() {
  if (blinkTimer !== null) window.clearTimeout(blinkTimer)
  const { delayMs, doubleBlink } = sampleWeibullBlinkDelayMs(props.mood === 'sleepy')
  blinkTimer = window.setTimeout(() => {
    isBlinking.value = true
    blinkEndTimer = window.setTimeout(() => {
      isBlinking.value = false
      if (doubleBlink) {
        doubleBlinkTimer = window.setTimeout(() => {
          isBlinking.value = true
          blinkEndTimer = window.setTimeout(() => {
            isBlinking.value = false
            scheduleNextBlink()
          }, 115)
        }, 145)
      } else {
        scheduleNextBlink()
      }
    }, 135)
  }, delayMs)
}

function triggerSquashStretch(sx = 1.13, sy = 0.88) {
  scaleXSpring.x = sx
  scaleYSpring.x = sy
  scaleXSpring.v = -1.2
  scaleYSpring.v = 1.4
  scaleXSpring.target = 1
  scaleYSpring.target = 1
}

function triggerEarTwitch(strength = 135) {
  earLSpring.impulse(-strength)
  earRSpring.impulse(strength * 0.9)
}

watch(
  () => props.bouncing,
  (val) => {
    if (val) {
      triggerSquashStretch(1.15, 0.86)
      triggerEarTwitch(110)
      tailSpring.impulse(90)
    }
  },
)

watch(
  () => props.actionSeq,
  () => {
    const act = props.actionPulse
    if (act === 'ear_twitch') {
      triggerEarTwitch(165)
    } else if (act === 'tail_turbo') {
      tailSpring.impulse(150)
      triggerSquashStretch(1.09, 0.92)
    } else if (act === 'sparkle') {
      triggerSquashStretch(1.12, 0.9)
      triggerEarTwitch(120)
    } else if (act === 'nod') {
      headSpring.impulse(75)
    } else if (act === 'hug') {
      triggerSquashStretch(0.95, 1.06)
    } else if (act === 'blush') {
      triggerEarTwitch(85)
    }
  },
)

function stepPhysics(nowMs: number) {
  if (!prevTimeMs) prevTimeMs = nowMs
  const dt = clamp((nowMs - prevTimeMs) / 1000, 0.004, 0.04)
  prevTimeMs = nowMs
  phaseClock += dt

  // Subtle random micro-saccade every 1.4~3.2s so eyes look organically alive
  if (nowMs >= nextSaccadeAt) {
    microSaccadeX = (Math.random() - 0.5) * 0.9
    microSaccadeY = (Math.random() - 0.5) * 0.65
    nextSaccadeAt = nowMs + 1400 + Math.random() * 1800
  }

  // Head target angle: mood pose + gaze follow + drag pendulum swing
  let moodHeadDeg = 0
  if (props.mood === 'thinking') moodHeadDeg = 5.5
  else if (props.mood === 'curious') moodHeadDeg = -7.5
  else if (props.mood === 'comfort') moodHeadDeg = -3.2
  else if (props.mood === 'shy') moodHeadDeg = -4.2
  else if (props.mood === 'sleepy') moodHeadDeg = 6.5 + Math.sin(phaseClock * 1.4) * 2.5
  else if (props.mood === 'pout') moodHeadDeg = -5.0
  else if (props.mood === 'dizzy') moodHeadDeg = Math.sin(phaseClock * 9.2) * 11.0
  else if (props.mood === 'excited') moodHeadDeg = Math.sin(phaseClock * 6.0) * 4.5

  headSpring.target = clamp(moodHeadDeg + props.gazeX * 1.15 + props.dragTiltDeg * 0.55, -24, 24)
  headAngle.value = headSpring.step(dt)

  // Ears target + spring follow from head acceleration
  let earBaseL = 0
  let earBaseR = 0
  if (props.mood === 'comfort' || props.mood === 'sleepy') {
    earBaseL = -10
    earBaseR = 10
  } else if (props.mood === 'happy' || props.mood === 'excited') {
    earBaseL = 5
    earBaseR = -5
  } else if (props.mood === 'curious') {
    earBaseL = 7
    earBaseR = -2
  } else if (props.mood === 'pout') {
    earBaseL = -12
    earBaseR = 12
  } else if (props.mood === 'shy') {
    earBaseL = -5
    earBaseR = 5
  }
  earLSpring.target = earBaseL - props.dragTiltDeg * 0.35
  earRSpring.target = earBaseR - props.dragTiltDeg * 0.35
  earLeftAngle.value = earLSpring.step(dt)
  earRightAngle.value = earRSpring.step(dt)

  // Fluffy tail continuous harmonic wag + drag inertia
  const wagRad = phaseClock * Math.PI * 2 * props.tailFreqHz
  tailSpring.target = Math.sin(wagRad) * props.tailAmpDeg - props.dragTiltDeg * 0.9
  tailAngle.value = tailSpring.step(dt)

  // Breathing & hop float
  if (props.mood === 'happy' || props.mood === 'excited') {
    bodyFloatY.value = -Math.abs(Math.sin(phaseClock * 5.2)) * 7.5
  } else if (props.mood === 'dizzy') {
    bodyFloatY.value = Math.sin(phaseClock * 8) * 3
    dizzySpin.value = (phaseClock * 260) % 360
  } else {
    const breathSpeed = props.mood === 'sleepy' ? 1.35 : 2.1
    bodyFloatY.value = Math.sin(phaseClock * breathSpeed) * props.breathAmpPx
  }

  bodyScaleX.value = scaleXSpring.step(dt)
  bodyScaleY.value = scaleYSpring.step(dt)

  // Smooth iris gaze spring
  let baseGazeX = props.gazeX + microSaccadeX
  let baseGazeY = props.gazeY + microSaccadeY
  if (props.mood === 'thinking') {
    baseGazeX = 2.6
    baseGazeY = -2.0
  } else if (props.mood === 'shy') {
    baseGazeX = -2.2
    baseGazeY = 1.4
  }
  gazeXSpring.target = clamp(baseGazeX, -3.8, 3.8)
  gazeYSpring.target = clamp(baseGazeY, -2.6, 2.6)
  eyeOffsetX.value = gazeXSpring.step(dt)
  eyeOffsetY.value = gazeYSpring.step(dt)

  // Syllable-cadence lip sync spring
  const talkTarget = props.speaking
    ? 1.4 + clamp(props.mouthOpenness || 0.65, 0.15, 1) * 3.1 + Math.sin(phaseClock * 24) * 0.45
    : 0.5
  mouthSpring.target = talkTarget
  mouthRy.value = clamp(mouthSpring.step(dt), 0.5, 5.2)

  rafId = window.requestAnimationFrame(stepPhysics)
}

const isBlinkFrame = computed(() => {
  return (
    props.mood !== 'happy' &&
    props.mood !== 'dizzy' &&
    props.mood !== 'excited' &&
    isBlinking.value
  )
})

const effectiveBlush = computed(() => {
  if (props.mood === 'shy') return Math.min(0.98, props.blushOpacity + 0.22)
  if (props.mood === 'pout') return Math.min(0.95, props.blushOpacity + 0.14)
  return clamp(props.blushOpacity, 0.35, 0.95)
})

onMounted(() => {
  scheduleNextBlink()
  if (props.interactive) {
    rafId = window.requestAnimationFrame(stepPhysics)
  }
})

onBeforeUnmount(() => {
  if (blinkTimer !== null) window.clearTimeout(blinkTimer)
  if (blinkEndTimer !== null) window.clearTimeout(blinkEndTimer)
  if (doubleBlinkTimer !== null) window.clearTimeout(doubleBlinkTimer)
  if (rafId !== null) window.cancelAnimationFrame(rafId)
})
</script>

<template>
  <div
    class="lian-figure-wrap"
    :class="[`mood-${mood}`, { 'is-speaking': speaking }]"
    :style="{ width: `${size}px`, height: `${Math.round((size * 260) / 240)}px` }"
  >
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 240 260"
      class="lian-svg"
      aria-label="玫瑰心狐娘恋恋"
    >
      <defs>
        <radialGradient :id="defId('lianComfortAura')" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stop-color="#ffdce8" stop-opacity="0.95" />
          <stop offset="65%" stop-color="#ffbcd3" stop-opacity="0.45" />
          <stop offset="100%" stop-color="#ffbcd3" stop-opacity="0" />
        </radialGradient>
        <linearGradient :id="defId('lianTailGrad')" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#ffbfd3" />
          <stop offset="55%" stop-color="#ff83aa" />
          <stop offset="100%" stop-color="#df5d89" />
        </linearGradient>
        <linearGradient :id="defId('lianHairMainGrad')" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#ffc3d5" />
          <stop offset="55%" stop-color="#fb92b3" />
          <stop offset="100%" stop-color="#e3648f" />
        </linearGradient>
        <linearGradient :id="defId('lianHairBackGrad')" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#f283a7" />
          <stop offset="100%" stop-color="#c94b78" />
        </linearGradient>
        <linearGradient :id="defId('lianEarInnerGrad')" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#ffeef4" />
          <stop offset="100%" stop-color="#ffc9db" />
        </linearGradient>
        <linearGradient :id="defId('lianSkinGrad')" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#fff4ef" />
          <stop offset="78%" stop-color="#ffece5" />
          <stop offset="100%" stop-color="#fbd9d0" />
        </linearGradient>
        <linearGradient :id="defId('lianIrisGrad')" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#581434" />
          <stop offset="52%" stop-color="#b92a62" />
          <stop offset="100%" stop-color="#ff6e9e" />
        </linearGradient>
        <linearGradient :id="defId('lianCardiganGrad')" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#ff9ab8" />
          <stop offset="100%" stop-color="#e8618e" />
        </linearGradient>
        <linearGradient :id="defId('lianSkirtGrad')" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stop-color="#cf4e7b" />
          <stop offset="100%" stop-color="#a2325b" />
        </linearGradient>
        <clipPath :id="defId('lianTailClip')">
          <path
            d="M98 198 C65 210 30 198 20 168 C11 140 24 106 46 92 C58 84 62 96 67 104 C75 118 65 142 82 158 C95 170 105 182 98 198 Z"
          />
        </clipPath>
      </defs>

      <!-- Warm Aura in comfort / shy mode -->
      <circle
        v-if="mood === 'comfort' || mood === 'shy'"
        cx="120"
        cy="140"
        r="102"
        :fill="urlRef('lianComfortAura')"
        class="lian-aura-pulse"
      />

      <!-- Procedural Body Root (float + drag swing + spring squash/stretch) -->
      <g
        :transform="`translate(120, ${142 + bodyFloatY}) rotate(${dragTiltDeg * 0.45}) scale(${bodyScaleX}, ${bodyScaleY}) translate(-120, -142)`"
      >
        <!-- 1. Fluffy Fox Tail (Spring-Damper Physics) -->
        <g :transform="`rotate(${tailAngle} 98 192)`">
          <path
            d="M98 198 C65 210 30 198 20 168 C11 140 24 106 46 92 C58 84 62 96 67 104 C75 118 65 142 82 158 C95 170 105 182 98 198 Z"
            :fill="urlRef('lianTailGrad')"
            stroke="#582c3e"
            stroke-width="2.7"
            stroke-linejoin="round"
          />
          <path
            d="M12 135 C22 126 32 136 42 125 C52 114 60 124 72 114 L68 78 L12 78 Z"
            fill="#fff8fb"
            :clip-path="urlRef('lianTailClip')"
          />
          <path
            d="M36 188 C52 200 80 202 96 194 C80 194 56 189 44 176 Z"
            fill="#c64372"
            opacity="0.3"
            :clip-path="urlRef('lianTailClip')"
          />
          <path
            d="M98 198 C65 210 30 198 20 168 C11 140 24 106 46 92 C58 84 62 96 67 104 C75 118 65 142 82 158 C95 170 105 182 98 198 Z"
            fill="none"
            stroke="#582c3e"
            stroke-width="2.7"
            stroke-linejoin="round"
          />
        </g>

        <!-- 2. Back Hair Curtain -->
        <g :transform="`rotate(${headAngle} 120 138)`">
          <path
            d="M62 94 C54 128 53 159 64 175 C73 167 82 173 88 163 L152 163 C158 173 167 167 176 175 C187 159 186 128 178 94 Z"
            :fill="urlRef('lianHairBackGrad')"
            stroke="#582c3e"
            stroke-width="2.6"
            stroke-linejoin="round"
          />
        </g>

        <!-- 3. Legs & Rose Mary-Jane Shoes (dangle slightly when dragged) -->
        <g :transform="`rotate(${-dragTiltDeg * 0.35} 120 218)`">
          <rect x="97" y="218" width="13" height="19" rx="5" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          <path d="M96 227 Q103.5 230 111 227 L111 237 L96 237 Z" fill="#ffffff" stroke="#582c3e" stroke-width="2.1" />
          <ellipse cx="101.5" cy="240.5" rx="10.5" ry="5.8" fill="#d94e7d" stroke="#582c3e" stroke-width="2.3" />
          <path d="M95 239 Q101.5 237 108 239" fill="none" stroke="#fff4f7" stroke-width="1.8" stroke-linecap="round" />

          <rect x="130" y="218" width="13" height="19" rx="5" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          <path d="M129 227 Q136.5 230 144 227 L144 237 L129 237 Z" fill="#ffffff" stroke="#582c3e" stroke-width="2.1" />
          <ellipse cx="138.5" cy="240.5" rx="10.5" ry="5.8" fill="#d94e7d" stroke="#582c3e" stroke-width="2.3" />
          <path d="M132 239 Q138.5 237 145 239" fill="none" stroke="#fff4f7" stroke-width="1.8" stroke-linecap="round" />
        </g>

        <!-- 4. Skirt with Lace Hem -->
        <g>
          <path
            d="M90 194 L150 194 L161 220 C140 226 100 226 79 220 Z"
            :fill="urlRef('lianSkirtGrad')"
            stroke="#582c3e"
            stroke-width="2.5"
            stroke-linejoin="round"
          />
          <path d="M104 196 L98 222" fill="none" stroke="#892147" stroke-width="1.8" stroke-linecap="round" opacity="0.62" />
          <path d="M120 196 L120 223" fill="none" stroke="#892147" stroke-width="1.8" stroke-linecap="round" opacity="0.62" />
          <path d="M136 196 L142 222" fill="none" stroke="#892147" stroke-width="1.8" stroke-linecap="round" opacity="0.62" />
          <path
            d="M81 220 Q88 227 95 221 Q103 227 111 221 Q120 228 129 221 Q137 227 145 221 Q152 227 159 220"
            fill="#fff8fa"
            stroke="#582c3e"
            stroke-width="2"
            stroke-linejoin="round"
          />
        </g>

        <!-- 5. Cardigan Torso & Heart Brooch -->
        <g>
          <path
            d="M91 156 C86 164 87 183 88 197 C106 201 134 201 152 197 C153 183 154 164 149 156 C135 153 105 153 91 156 Z"
            :fill="urlRef('lianCardiganGrad')"
            stroke="#582c3e"
            stroke-width="2.5"
            stroke-linejoin="round"
          />
          <path d="M108 155 L120 182 L132 155 Z" fill="#fff9fb" stroke="#582c3e" stroke-width="2" stroke-linejoin="round" />
          <path d="M101 154 C97 165 110 168 119 162 Z" fill="#ffffff" stroke="#582c3e" stroke-width="2.1" stroke-linejoin="round" />
          <path d="M139 154 C143 165 130 168 121 162 Z" fill="#ffffff" stroke="#582c3e" stroke-width="2.1" stroke-linejoin="round" />
          <circle cx="120" cy="187" r="2.2" fill="#ffe6ee" stroke="#8a2c4f" stroke-width="1.1" />
          <circle cx="120" cy="194" r="2.2" fill="#ffe6ee" stroke="#8a2c4f" stroke-width="1.1" />
          <path d="M119 164 L106 159 L109 169 Z" fill="#ff477e" stroke="#582c3e" stroke-width="1.8" stroke-linejoin="round" />
          <path d="M121 164 L134 159 L131 169 Z" fill="#ff477e" stroke="#582c3e" stroke-width="1.8" stroke-linejoin="round" />
          <path
            d="M114.5 163 C114.5 159.5 119 158.5 120 161.5 C121 158.5 125.5 159.5 125.5 163 C125.5 167 120 171 120 171 C120 171 114.5 167 114.5 163 Z"
            fill="#ff2e6e"
            stroke="#582c3e"
            stroke-width="1.8"
          />
          <circle cx="117.5" cy="162" r="1.2" fill="#ffffff" opacity="0.85" />
        </g>

        <!-- 6. Head Group (Spring-Damper Head Tilt) -->
        <g :transform="`rotate(${headAngle} 120 138)`">
          <rect x="113" y="143" width="14" height="15" rx="6" fill="#fae0d6" stroke="#582c3e" stroke-width="2.2" />
          <path d="M114 146 Q120 151 126 146" fill="none" stroke="#e3b1a6" stroke-width="3" opacity="0.7" />

          <!-- Left Fox Ear (Spring-Damper) -->
          <g :transform="`rotate(${earLeftAngle} 74 62)`">
            <path
              d="M58 70 C50 42 50 18 58 14 C69 10 92 26 102 48 Z"
              :fill="urlRef('lianHairMainGrad')"
              stroke="#582c3e"
              stroke-width="2.7"
              stroke-linejoin="round"
            />
            <path d="M64 62 C59 42 60 27 65 24 C73 22 88 34 94 49 Z" :fill="urlRef('lianEarInnerGrad')" />
            <path d="M68 58 C69 50 75 49 76 55 C79 49 85 50 86 57 Z" fill="#fffafc" />
          </g>

          <!-- Right Fox Ear (Spring-Damper) -->
          <g :transform="`rotate(${earRightAngle} 166 62)`">
            <path
              d="M182 70 C190 42 190 18 182 14 C171 10 148 26 138 48 Z"
              :fill="urlRef('lianHairMainGrad')"
              stroke="#582c3e"
              stroke-width="2.7"
              stroke-linejoin="round"
            />
            <path d="M176 62 C181 42 180 27 175 24 C167 22 152 34 146 49 Z" :fill="urlRef('lianEarInnerGrad')" />
            <path d="M172 58 C171 50 165 49 164 55 C161 49 155 50 154 57 Z" fill="#fffafc" />
          </g>

          <!-- Face Silhouette -->
          <path
            d="M68 92 C68 58 90 43 120 43 C150 43 172 58 172 92 C173 125 154 149 120 149 C86 149 67 125 68 92 Z"
            :fill="urlRef('lianSkinGrad')"
            stroke="#582c3e"
            stroke-width="2.7"
            stroke-linejoin="round"
          />

          <!-- Dynamic PAD-Modulated Rosy Blushes -->
          <g :opacity="effectiveBlush">
            <ellipse cx="82" cy="121" :rx="mood === 'shy' ? 14 : 11" :ry="mood === 'shy' ? 7 : 5.8" fill="#ff749b" />
            <line x1="76" y1="123" x2="79" y2="118.5" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" opacity="0.85" />
            <line x1="81" y1="123" x2="84" y2="118.5" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" opacity="0.85" />
            <line v-if="mood === 'shy'" x1="86" y1="123" x2="89" y2="118.5" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" opacity="0.85" />
            <ellipse cx="158" cy="121" :rx="mood === 'shy' ? 14 : 11" :ry="mood === 'shy' ? 7 : 5.8" fill="#ff749b" />
            <line x1="153" y1="123" x2="156" y2="118.5" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" opacity="0.85" />
            <line x1="158" y1="123" x2="161" y2="118.5" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" opacity="0.85" />
            <line v-if="mood === 'shy'" x1="163" y1="123" x2="166" y2="118.5" stroke="#ffffff" stroke-width="1.5" stroke-linecap="round" opacity="0.85" />
          </g>

          <!-- Cute Nose Dot -->
          <path d="M119 119.5 Q120 121.5 121 119.5" fill="none" stroke="#c98585" stroke-width="1.8" stroke-linecap="round" />

          <!-- Eyebrows (10 Mood Variations) -->
          <template v-if="mood === 'happy' || mood === 'excited'">
            <path d="M83 86 Q95 80 106 86" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M134 86 Q145 80 157 86" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>
          <template v-else-if="mood === 'comfort' || mood === 'shy'">
            <path d="M83 92 Q95 87 105 94" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M135 94 Q145 87 157 92" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>
          <template v-else-if="mood === 'pout'">
            <path d="M83 87 L106 93" fill="none" stroke="#b85b7c" stroke-width="2.4" stroke-linecap="round" />
            <path d="M157 87 L134 93" fill="none" stroke="#b85b7c" stroke-width="2.4" stroke-linecap="round" />
          </template>
          <template v-else-if="mood === 'thinking' || mood === 'curious'">
            <path d="M83 90 Q94 87 105 90" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M134 84 Q146 79 157 86" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>
          <template v-else-if="mood === 'sleepy'">
            <path d="M84 93 Q95 90 105 94" fill="none" stroke="#b85b7c" stroke-width="2" stroke-linecap="round" />
            <path d="M135 94 Q145 90 156 93" fill="none" stroke="#b85b7c" stroke-width="2" stroke-linecap="round" />
          </template>
          <template v-else>
            <path d="M84 89 Q95 85 105 89" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M135 89 Q145 85 156 89" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>

          <!-- Eyes (10 States + Real-Time Gaze Tracking) -->
          <template v-if="mood === 'happy'">
            <path d="M80 112 Q94 96 108 112" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
            <path d="M77 108 L83 111" fill="none" stroke="#4d1f33" stroke-width="2.5" stroke-linecap="round" />
            <path d="M132 112 Q146 96 160 112" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
            <path d="M157 111 L163 108" fill="none" stroke="#4d1f33" stroke-width="2.5" stroke-linecap="round" />
          </template>
          <template v-else-if="mood === 'dizzy'">
            <!-- Spiral @_@ Eyes -->
            <g :transform="`rotate(${dizzySpin} 94 109)`">
              <path
                d="M94 109 m0 -9 a9 9 0 1 1 -8.2 5.4 a6 6 0 1 1 5.4 3.4 a3 3 0 1 1 -2.4 -1.6"
                fill="none"
                stroke="#4d1f33"
                stroke-width="2.6"
                stroke-linecap="round"
              />
            </g>
            <g :transform="`rotate(${-dizzySpin} 146 109)`">
              <path
                d="M146 109 m0 -9 a9 9 0 1 1 -8.2 5.4 a6 6 0 1 1 5.4 3.4 a3 3 0 1 1 -2.4 -1.6"
                fill="none"
                stroke="#4d1f33"
                stroke-width="2.6"
                stroke-linecap="round"
              />
            </g>
          </template>
          <template v-else-if="isBlinkFrame || mood === 'sleepy'">
            <template v-if="mood === 'sleepy' && !isBlinkFrame">
              <!-- Half-lidded drowsy eyes -->
              <ellipse cx="94" cy="111" rx="11.5" ry="7.5" fill="#ffffff" />
              <ellipse cx="94" cy="112" rx="8.8" ry="6.2" :fill="urlRef('lianIrisGrad')" />
              <circle cx="90.5" cy="110" r="2.2" fill="#ffffff" />
              <path d="M80 107 Q94 111 108 107" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
              <ellipse cx="146" cy="111" rx="11.5" ry="7.5" fill="#ffffff" />
              <ellipse cx="146" cy="112" rx="8.8" ry="6.2" :fill="urlRef('lianIrisGrad')" />
              <circle cx="142.5" cy="110" r="2.2" fill="#ffffff" />
              <path d="M132 107 Q146 111 160 107" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
            </template>
            <template v-else>
              <path d="M80 111 Q94 118 108 109" fill="none" stroke="#4d1f33" stroke-width="3.6" stroke-linecap="round" />
              <path d="M78 108 L83 112" fill="none" stroke="#4d1f33" stroke-width="2.3" stroke-linecap="round" />
              <path d="M132 109 Q146 118 160 111" fill="none" stroke="#4d1f33" stroke-width="3.6" stroke-linecap="round" />
              <path d="M157 112 L162 108" fill="none" stroke="#4d1f33" stroke-width="2.3" stroke-linecap="round" />
            </template>
          </template>
          <template v-else>
            <!-- Left Open Eye with Smooth Gaze Tracking -->
            <g>
              <ellipse cx="94" cy="109" rx="12.5" ry="14" fill="#ffffff" />
              <g :transform="`translate(${eyeOffsetX}, ${eyeOffsetY})`">
                <ellipse cx="94" cy="110" rx="10.4" ry="12.4" :fill="urlRef('lianIrisGrad')" />
                <ellipse cx="94" cy="115.5" rx="7.2" ry="4.5" fill="#ff9bc0" opacity="0.62" />
                <ellipse cx="94" cy="108.5" rx="4.4" ry="5.4" fill="#3b0c22" />
                <path
                  v-if="mood === 'excited'"
                  d="M94 102 L96 107 L101 109 L96 111 L94 116 L92 111 L87 109 L92 107 Z"
                  fill="#ffe270"
                />
                <circle cx="89.5" cy="103.5" r="3.9" fill="#ffffff" />
                <circle cx="99.3" cy="114.2" r="2.0" fill="#ffffff" />
                <circle cx="98.4" cy="104.2" r="1.1" fill="#ffd9e8" />
              </g>
              <path d="M79 107 C84 93 104 93 109 107" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
              <path d="M76.5 103.5 L83 107" fill="none" stroke="#4d1f33" stroke-width="2.6" stroke-linecap="round" />
            </g>
            <!-- Right Open Eye with Smooth Gaze Tracking -->
            <g>
              <ellipse cx="146" cy="109" rx="12.5" ry="14" fill="#ffffff" />
              <g :transform="`translate(${eyeOffsetX}, ${eyeOffsetY})`">
                <ellipse cx="146" cy="110" rx="10.4" ry="12.4" :fill="urlRef('lianIrisGrad')" />
                <ellipse cx="146" cy="115.5" rx="7.2" ry="4.5" fill="#ff9bc0" opacity="0.62" />
                <ellipse cx="146" cy="108.5" rx="4.4" ry="5.4" fill="#3b0c22" />
                <path
                  v-if="mood === 'excited'"
                  d="M146 102 L148 107 L153 109 L148 111 L146 116 L144 111 L139 109 L144 107 Z"
                  fill="#ffe270"
                />
                <circle cx="141.5" cy="103.5" r="3.9" fill="#ffffff" />
                <circle cx="151.3" cy="114.2" r="2.0" fill="#ffffff" />
                <circle cx="150.4" cy="104.2" r="1.1" fill="#ffd9e8" />
              </g>
              <path d="M131 107 C136 93 156 93 161 107" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
              <path d="M157 107 L163.5 103.5" fill="none" stroke="#4d1f33" stroke-width="2.6" stroke-linecap="round" />
            </g>
          </template>

          <!-- Mouth (Syllable Lip-Sync + 10 Moods) -->
          <g>
            <template v-if="speaking && mood !== 'happy' && mood !== 'excited'">
              <ellipse cx="120" cy="132" rx="4.6" :ry="mouthRy" fill="#d9587f" stroke="#6d233d" stroke-width="1.9" />
            </template>
            <template v-else-if="mood === 'happy' || mood === 'excited'">
              <path d="M111 128 C114 139.5 126 139.5 129 128 Z" fill="#d44b74" stroke="#6d233d" stroke-width="2" stroke-linejoin="round" />
              <path d="M115 134 C118 132 122 132 125 134 C123 137.5 117 137.5 115 134 Z" fill="#ff9bb8" />
            </template>
            <template v-else-if="mood === 'thinking' || mood === 'curious'">
              <ellipse cx="121.5" cy="132.5" rx="3.2" ry="3.8" fill="#d9587f" stroke="#6d233d" stroke-width="1.9" />
            </template>
            <template v-else-if="mood === 'sleepy'">
              <ellipse cx="120" cy="133" rx="4.2" ry="5.2" fill="#e57c9c" stroke="#6d233d" stroke-width="1.8" />
            </template>
            <template v-else-if="mood === 'pout'">
              <path d="M114 134 Q120 128 126 134" fill="none" stroke="#8c3b55" stroke-width="2.4" stroke-linecap="round" />
            </template>
            <template v-else-if="mood === 'dizzy'">
              <path d="M112 133 Q116 129 120 133 Q124 137 128 133" fill="none" stroke="#8c3b55" stroke-width="2.3" stroke-linecap="round" />
            </template>
            <template v-else-if="mood === 'comfort' || mood === 'shy'">
              <path d="M114 131 Q120 136.5 126 131" fill="none" stroke="#8c3b55" stroke-width="2.2" stroke-linecap="round" />
            </template>
            <template v-else>
              <path d="M113 130 Q116.5 134.5 120 130.5 Q123.5 134.5 127 130" fill="none" stroke="#8c3b55" stroke-width="2.2" stroke-linecap="round" />
              <path d="M117.5 133.5 C119 136.5 121 136.5 122.5 133.5 Z" fill="#ff98b5" />
            </template>
          </g>

          <!-- Soft Forehead Shadow -->
          <path
            d="M72 86 C82 95 95 95 104 89 C110 97 122 98 130 90 C142 97 156 96 168 86 L168 78 L72 78 Z"
            fill="#efb8c5"
            opacity="0.42"
          />

          <!-- Front Hair & Side Locks -->
          <g>
            <path d="M73 74 C60 95 57 126 67 151 C73 144 76 130 76 112 Z" :fill="urlRef('lianHairMainGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <path d="M167 74 C180 95 183 126 173 151 C167 144 164 130 164 112 Z" :fill="urlRef('lianHairMainGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <path
              d="M64 92 C63 54 88 38 120 38 C152 38 177 54 176 92 C169 87 163 79 158 72 C156 84 148 92 141 94 C140 84 135 76 131 71 C128 85 120 94 114 96 C112 85 107 76 103 70 C98 84 90 91 81 92 C78 83 76 77 73 73 C70 81 67 88 64 92 Z"
              :fill="urlRef('lianHairMainGrad')"
              stroke="#582c3e"
              stroke-width="2.7"
              stroke-linejoin="round"
            />
            <path d="M84 58 Q103 49 116 54" fill="none" stroke="#fff7fa" stroke-width="4.2" stroke-linecap="round" opacity="0.78" />
            <path d="M126 54 Q141 51 154 59" fill="none" stroke="#fff7fa" stroke-width="3.6" stroke-linecap="round" opacity="0.72" />
            <path d="M119 38 C117 26 127 20 133 26 C127 27 123 32 123 39" fill="none" stroke="#582c3e" stroke-width="2.5" stroke-linecap="round" />
            <path d="M120 38 C119 28 126 24 130 27" fill="none" stroke="#ff9dbb" stroke-width="2.2" stroke-linecap="round" />
          </g>

          <!-- Signature Heart Hairclip -->
          <g transform="translate(152, 70) rotate(16)">
            <rect x="-12" y="-3" width="24" height="5.5" rx="2.7" fill="#ffd970" stroke="#582c3e" stroke-width="1.6" />
            <path
              d="M-7 -4 C-7 -9 0 -10 1 -5.5 C2 -10 9 -9 9 -4 C9 2 1 6 1 6 C1 6 -7 2 -7 -4 Z"
              fill="#ff3878"
              stroke="#582c3e"
              stroke-width="1.8"
            />
            <circle cx="-2.5" cy="-4.5" r="1.4" fill="#ffffff" opacity="0.9" />
          </g>
        </g>

        <!-- 7. Arms & State Props -->
        <template v-if="mood === 'happy' || mood === 'excited'">
          <g>
            <path d="M90 157 C74 155 56 144 51 128 C49 120 59 118 65 125 C72 135 79 144 90 150 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <path d="M52 130 Q59 135 66 130" fill="none" stroke="#fff7fa" stroke-width="3" stroke-linecap="round" />
            <circle cx="55" cy="121" r="7.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
          <g>
            <path d="M150 157 C166 155 184 144 189 128 C191 120 181 118 175 125 C168 135 161 144 150 150 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <path d="M174 130 Q181 135 188 130" fill="none" stroke="#fff7fa" stroke-width="3" stroke-linecap="round" />
            <circle cx="185" cy="121" r="7.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
        </template>

        <template v-else-if="mood === 'shy'">
          <!-- Shy hands lightly touching cheeks -->
          <g>
            <path d="M91 158 C76 164 70 152 77 137 L87 141 C84 150 87 154 93 156 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.4" stroke-linejoin="round" />
            <circle cx="81" cy="134" r="7.4" fill="#fff2ec" stroke="#582c3e" stroke-width="2.2" />
          </g>
          <g>
            <path d="M149 158 C164 164 170 152 163 137 L153 141 C156 150 153 154 147 156 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.4" stroke-linejoin="round" />
            <circle cx="159" cy="134" r="7.4" fill="#fff2ec" stroke="#582c3e" stroke-width="2.2" />
          </g>
        </template>

        <template v-else-if="mood === 'thinking' || mood === 'curious'">
          <g>
            <path d="M90 158 C78 166 68 184 72 198 C74 206 83 204 86 196 C88 186 91 174 93 166 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <path d="M72 195 Q79 199 85 195" fill="none" stroke="#fff7fa" stroke-width="3.2" stroke-linecap="round" />
            <circle cx="77" cy="204" r="7.2" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
          <g>
            <path d="M150 158 C166 164 173 177 166 184 C159 190 144 178 135 159 L142 153 C149 165 155 170 158 172 C156 168 153 164 148 162 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <circle cx="136" cy="153" r="7.5" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
        </template>

        <template v-else-if="mood === 'comfort'">
          <g>
            <path d="M90 159 C76 168 78 189 98 191 L103 181 C89 180 88 172 94 165 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.4" stroke-linejoin="round" />
            <path d="M150 159 C164 168 162 189 142 191 L137 181 C151 180 152 172 146 165 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.4" stroke-linejoin="round" />
            <rect x="103" y="167" width="34" height="28" rx="8" fill="#fffaf8" stroke="#582c3e" stroke-width="2.3" />
            <path d="M137 174 C145 174 145 186 137 186" fill="none" stroke="#582c3e" stroke-width="2.3" stroke-linecap="round" />
            <ellipse cx="120" cy="170.5" rx="12.5" ry="3.2" fill="#9c5a43" />
            <path d="M114.5 179.5 C114.5 176.5 119 175.8 120 178.5 C121 175.8 125.5 176.5 125.5 179.5 C125.5 183 120 186.8 120 186.8 C120 186.8 114.5 183 114.5 179.5 Z" fill="#ff5c8f" />
            <circle cx="101.5" cy="184" r="6.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.2" />
            <circle cx="138.5" cy="184" r="6.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.2" />
            <g class="lian-steam-group">
              <path d="M113 161 C110 156 115 152 112 147" fill="none" stroke="#ffd8e4" stroke-width="2.4" stroke-linecap="round" />
              <path d="M126 161 C129 156 124 152 127 147" fill="none" stroke="#ffd8e4" stroke-width="2.4" stroke-linecap="round" />
            </g>
          </g>
        </template>

        <template v-else>
          <g>
            <path d="M90 158 C78 164 67 183 70 198 C72 206 82 204 85 196 C88 186 91 174 93 166 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <path d="M70 195 Q77 199 84 195" fill="none" stroke="#fff7fa" stroke-width="3.2" stroke-linecap="round" />
            <circle cx="76" cy="204" r="7.2" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
          <g class="lian-wave-arm" style="transform-origin: 152px 154px">
            <path d="M150 158 C166 158 186 150 191 134 C193 126 183 123 177 130 C170 139 162 146 151 151 Z" :fill="urlRef('lianCardiganGrad')" stroke="#582c3e" stroke-width="2.5" stroke-linejoin="round" />
            <path d="M175 135 Q182 140 189 135" fill="none" stroke="#fff7fa" stroke-width="3" stroke-linecap="round" />
            <circle cx="187" cy="126" r="7.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
        </template>
      </g>

      <!-- 8. Expressive Foreground Accents -->
      <g v-if="mood === 'happy' || mood === 'excited'" class="lian-happy-sparkles">
        <path d="M24 66 C24 59 34 57 36 64 C38 57 48 59 48 66 C48 74 36 82 36 82 C36 82 24 74 24 66 Z" fill="#ff5c93" stroke="#ffffff" stroke-width="1.8" />
        <path d="M196 50 C196 44 204 42 206 48 C208 42 216 44 216 50 C216 56 206 63 206 63 C206 63 196 56 196 50 Z" fill="#ff87b0" stroke="#ffffff" stroke-width="1.6" />
        <path d="M212 108 L215 115 L222 118 L215 121 L212 128 L209 121 L202 118 L209 115 Z" fill="#ffd866" stroke="#fff9df" stroke-width="1" />
        <path d="M24 106 L26.5 112 L32 114.5 L26.5 117 L24 123 L21.5 117 L16 114.5 L21.5 112 Z" fill="#ffd866" stroke="#fff9df" stroke-width="1" />
      </g>

      <g v-else-if="mood === 'thinking' || mood === 'curious'" class="lian-think-bubble">
        <circle cx="187" cy="64" r="3.6" fill="#fff7fa" stroke="#f0729b" stroke-width="1.6" />
        <circle cx="195" cy="54" r="5.2" fill="#fff7fa" stroke="#f0729b" stroke-width="1.8" />
        <circle cx="211" cy="36" r="16" fill="#fff7fa" stroke="#e95c8c" stroke-width="2.2" />
        <text x="211" y="42.5" text-anchor="middle" font-family="PingFang SC, Arial, sans-serif" font-size="19" font-weight="800" fill="#d93f74">?</text>
      </g>

      <g v-else-if="mood === 'sleepy'" class="lian-sleepy-zzz">
        <text x="184" y="66" font-family="Arial, sans-serif" font-size="14" font-weight="800" fill="#b46e98">z</text>
        <text x="197" y="48" font-family="Arial, sans-serif" font-size="19" font-weight="800" fill="#9a5080">Z</text>
        <text x="212" y="29" font-family="Arial, sans-serif" font-size="24" font-weight="800" fill="#7d3b66">Z</text>
      </g>

      <g v-else-if="mood === 'pout'" class="lian-pout-pop">
        <circle cx="204" cy="40" r="14" fill="#fff4f6" stroke="#e11d48" stroke-width="2" />
        <text x="204" y="46" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" font-weight="900" fill="#e11d48">!</text>
      </g>

      <g v-else-if="mood === 'dizzy'" class="lian-dizzy-stars">
        <ellipse cx="120" cy="24" rx="52" ry="11" fill="none" stroke="#ffd866" stroke-width="2" stroke-dasharray="6 5" opacity="0.85" />
        <path d="M76 22 L78.5 27 L84 29 L78.5 31 L76 36 L73.5 31 L68 29 L73.5 27 Z" fill="#ffd866" stroke="#fff7d6" stroke-width="1" />
        <path d="M166 18 L168.5 23 L174 25 L168.5 27 L166 32 L163.5 27 L158 25 L163.5 23 Z" fill="#ff9ac0" stroke="#ffffff" stroke-width="1" />
      </g>

      <g v-else-if="mood === 'shy'" class="lian-happy-sparkles">
        <path d="M196 56 C196 51 203 50 205 55 C207 50 214 51 214 56 C214 62 205 68 205 68 C205 68 196 62 196 56 Z" fill="#ff74a4" stroke="#ffffff" stroke-width="1.4" />
      </g>
    </svg>
  </div>
</template>

<style scoped>
.lian-figure-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  user-select: none;
  pointer-events: none;
  filter: drop-shadow(0 8px 16px rgba(173, 45, 92, 0.18));
}

.lian-svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

.lian-wave-arm {
  animation: lian-hand-wave 3.4s ease-in-out infinite;
}

.lian-think-bubble,
.lian-pout-pop {
  animation: lian-think-pulse 1.5s ease-in-out infinite;
}

.lian-happy-sparkles {
  animation: lian-sparkle-pop 1s ease-in-out infinite alternate;
}

.lian-sleepy-zzz {
  animation: lian-zzz-float 2.6s ease-in-out infinite;
}

.lian-dizzy-stars {
  animation: lian-dizzy-sway 0.9s ease-in-out infinite alternate;
}

.lian-steam-group {
  animation: lian-steam-rise 2.2s ease-in-out infinite;
}

.lian-aura-pulse {
  animation: lian-aura-glow 2.4s ease-in-out infinite;
}

@keyframes lian-hand-wave {
  0%,
  72%,
  100% {
    transform: rotate(0deg);
  }
  78% {
    transform: rotate(-12deg);
  }
  85% {
    transform: rotate(8deg);
  }
  92% {
    transform: rotate(-8deg);
  }
}

@keyframes lian-think-pulse {
  0%,
  100% {
    transform: translateY(0px) scale(1);
  }
  50% {
    transform: translateY(-3px) scale(1.06);
  }
}

@keyframes lian-sparkle-pop {
  0% {
    opacity: 0.78;
    transform: scale(0.95);
  }
  100% {
    opacity: 1;
    transform: scale(1.07);
  }
}

@keyframes lian-zzz-float {
  0%,
  100% {
    opacity: 0.55;
    transform: translate(0, 3px);
  }
  50% {
    opacity: 1;
    transform: translate(3px, -5px);
  }
}

@keyframes lian-dizzy-sway {
  0% {
    transform: translateX(-3px) rotate(-3deg);
  }
  100% {
    transform: translateX(3px) rotate(3deg);
  }
}

@keyframes lian-steam-rise {
  0%,
  100% {
    opacity: 0.45;
    transform: translateY(2px);
  }
  50% {
    opacity: 0.95;
    transform: translateY(-4px);
  }
}

@keyframes lian-aura-glow {
  0%,
  100% {
    opacity: 0.6;
    transform: scale(0.96);
    transform-origin: 120px 140px;
  }
  50% {
    opacity: 0.95;
    transform: scale(1.03);
    transform-origin: 120px 140px;
  }
}
</style>
