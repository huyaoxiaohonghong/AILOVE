<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import type { MascotMood } from '@/stores/mascot'

const props = withDefaults(
  defineProps<{
    mood?: MascotMood
    speaking?: boolean
    size?: number
    bouncing?: boolean
  }>(),
  {
    mood: 'idle',
    speaking: false,
    size: 112,
    bouncing: false,
  },
)

const uid = useId()
const defId = (name: string) => `${name}-${uid}`
const urlRef = (name: string) => `url(#${name}-${uid})`

const isBlinking = ref(false)
let blinkScheduleTimer: number | null = null
let blinkOpenTimer: number | null = null

const isBlinkFrame = computed(() => {
  return (props.mood === 'idle' || props.mood === 'comfort') && isBlinking.value
})

const effectiveEyesClosed = computed(() => isBlinkFrame.value || props.mood === 'happy')

const headRotate = computed(() => {
  if (props.mood === 'thinking') return 4
  if (props.mood === 'comfort') return -2.5
  return 0
})

const leftEarRotate = computed(() => {
  if (props.mood === 'comfort') return -7
  if (props.mood === 'happy') return 4
  return 0
})

const rightEarRotate = computed(() => {
  if (props.mood === 'comfort') return 7
  if (props.mood === 'happy') return -4
  return 0
})

function scheduleNextBlink() {
  const delay = 2900 + Math.random() * 1700
  blinkScheduleTimer = window.setTimeout(() => {
    isBlinking.value = true
    blinkOpenTimer = window.setTimeout(() => {
      isBlinking.value = false
      scheduleNextBlink()
    }, 140)
  }, delay)
}

onMounted(() => {
  scheduleNextBlink()
})

onBeforeUnmount(() => {
  if (blinkScheduleTimer !== null) window.clearTimeout(blinkScheduleTimer)
  if (blinkOpenTimer !== null) window.clearTimeout(blinkOpenTimer)
})
</script>

<template>
  <div
    class="lian-figure-wrap"
    :class="[
      `mood-${mood}`,
      {
        'is-speaking': speaking,
        'is-bouncing': bouncing,
      },
    ]"
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

      <!-- Warm background aura in comfort mode -->
      <circle
        v-if="mood === 'comfort'"
        cx="120"
        cy="140"
        r="102"
        :fill="urlRef('lianComfortAura')"
        class="lian-aura-pulse"
      />

      <g class="lian-body-float">
        <!-- 1. Fluffy Fox Tail (sways smoothly) -->
        <g class="lian-tail-group" style="transform-origin: 98px 192px">
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
        <g :transform="`rotate(${headRotate} 120 138)`">
          <path
            d="M62 94 C54 128 53 159 64 175 C73 167 82 173 88 163 L152 163 C158 173 167 167 176 175 C187 159 186 128 178 94 Z"
            :fill="urlRef('lianHairBackGrad')"
            stroke="#582c3e"
            stroke-width="2.6"
            stroke-linejoin="round"
          />
        </g>

        <!-- 3. Legs & Rose Mary-Jane Shoes -->
        <g>
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

        <!-- 5. Cardigan Torso & Collar + Heart Brooch -->
        <g>
          <path
            d="M91 156 C86 164 87 183 88 197 C106 201 134 201 152 197 C153 183 154 164 149 156 C135 153 105 153 91 156 Z"
            :fill="urlRef('lianCardiganGrad')"
            stroke="#582c3e"
            stroke-width="2.5"
            stroke-linejoin="round"
          />
          <path d="M108 155 L120 182 L132 155 Z" fill="#fff9fb" stroke="#582c3e" stroke-width="2" stroke-linejoin="round" />
          <path
            d="M101 154 C97 165 110 168 119 162 Z"
            fill="#ffffff"
            stroke="#582c3e"
            stroke-width="2.1"
            stroke-linejoin="round"
          />
          <path
            d="M139 154 C143 165 130 168 121 162 Z"
            fill="#ffffff"
            stroke="#582c3e"
            stroke-width="2.1"
            stroke-linejoin="round"
          />
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

        <!-- 6. Head Group -->
        <g :transform="`rotate(${headRotate} 120 138)`" class="lian-head-group">
          <rect x="113" y="143" width="14" height="15" rx="6" fill="#fae0d6" stroke="#582c3e" stroke-width="2.2" />
          <path d="M114 146 Q120 151 126 146" fill="none" stroke="#e3b1a6" stroke-width="3" opacity="0.7" />

          <!-- Left Fox Ear -->
          <g :transform="`rotate(${leftEarRotate} 74 62)`">
            <g class="lian-ear-left" style="transform-origin: 74px 62px">
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
          </g>

          <!-- Right Fox Ear -->
          <g :transform="`rotate(${rightEarRotate} 166 62)`">
            <g class="lian-ear-right" style="transform-origin: 166px 62px">
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
          </g>

          <!-- Face Silhouette -->
          <path
            d="M68 92 C68 58 90 43 120 43 C150 43 172 58 172 92 C173 125 154 149 120 149 C86 149 67 125 68 92 Z"
            :fill="urlRef('lianSkinGrad')"
            stroke="#582c3e"
            stroke-width="2.7"
            stroke-linejoin="round"
          />

          <!-- Rosy Blushes -->
          <g opacity="0.72">
            <ellipse cx="82" cy="121" rx="11" ry="5.8" fill="#ff84a5" />
            <line x1="77" y1="123" x2="80" y2="119" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" opacity="0.8" />
            <line x1="82" y1="123" x2="85" y2="119" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" opacity="0.8" />
            <ellipse cx="158" cy="121" rx="11" ry="5.8" fill="#ff84a5" />
            <line x1="154" y1="123" x2="157" y2="119" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" opacity="0.8" />
            <line x1="159" y1="123" x2="162" y2="119" stroke="#ffffff" stroke-width="1.4" stroke-linecap="round" opacity="0.8" />
          </g>

          <!-- Nose dot -->
          <path d="M119 119.5 Q120 121.5 121 119.5" fill="none" stroke="#c98585" stroke-width="1.8" stroke-linecap="round" />

          <!-- Eyebrows -->
          <template v-if="mood === 'happy'">
            <path d="M83 87 Q95 82 106 87" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M134 87 Q145 82 157 87" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>
          <template v-else-if="mood === 'comfort'">
            <path d="M83 92 Q95 87 105 94" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M135 94 Q145 87 157 92" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>
          <template v-else-if="mood === 'thinking'">
            <path d="M83 90 Q94 87 105 90" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M134 85 Q146 80 157 86" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>
          <template v-else>
            <path d="M84 89 Q95 85 105 89" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
            <path d="M135 89 Q145 85 156 89" fill="none" stroke="#b85b7c" stroke-width="2.2" stroke-linecap="round" />
          </template>

          <!-- Eyes -->
          <template v-if="mood === 'happy'">
            <path d="M80 112 Q94 96 108 112" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
            <path d="M77 108 L83 111" fill="none" stroke="#4d1f33" stroke-width="2.5" stroke-linecap="round" />
            <path d="M132 112 Q146 96 160 112" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
            <path d="M157 111 L163 108" fill="none" stroke="#4d1f33" stroke-width="2.5" stroke-linecap="round" />
          </template>
          <template v-else-if="isBlinkFrame">
            <path d="M80 111 Q94 118 108 109" fill="none" stroke="#4d1f33" stroke-width="3.6" stroke-linecap="round" />
            <path d="M78 108 L83 112" fill="none" stroke="#4d1f33" stroke-width="2.3" stroke-linecap="round" />
            <path d="M132 109 Q146 118 160 111" fill="none" stroke="#4d1f33" stroke-width="3.6" stroke-linecap="round" />
            <path d="M157 112 L162 108" fill="none" stroke="#4d1f33" stroke-width="2.3" stroke-linecap="round" />
          </template>
          <template v-else-if="!effectiveEyesClosed">
            <!-- Left Open Eye -->
            <g>
              <ellipse cx="94" cy="109" rx="12.5" ry="14" fill="#ffffff" />
              <g :transform="mood === 'thinking' ? 'translate(2.4, -1.8)' : undefined">
                <ellipse cx="94" cy="110" rx="10.4" ry="12.4" :fill="urlRef('lianIrisGrad')" />
                <ellipse cx="94" cy="115.5" rx="7.2" ry="4.5" fill="#ff9bc0" opacity="0.62" />
                <ellipse cx="94" cy="108.5" rx="4.4" ry="5.4" fill="#3b0c22" />
                <circle cx="89.5" cy="103.5" r="3.9" fill="#ffffff" />
                <circle cx="99.3" cy="114.2" r="2.0" fill="#ffffff" />
                <circle cx="98.4" cy="104.2" r="1.1" fill="#ffd9e8" />
              </g>
              <path d="M79 107 C84 93 104 93 109 107" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
              <path d="M76.5 103.5 L83 107" fill="none" stroke="#4d1f33" stroke-width="2.6" stroke-linecap="round" />
            </g>
            <!-- Right Open Eye -->
            <g>
              <ellipse cx="146" cy="109" rx="12.5" ry="14" fill="#ffffff" />
              <g :transform="mood === 'thinking' ? 'translate(2.4, -1.8)' : undefined">
                <ellipse cx="146" cy="110" rx="10.4" ry="12.4" :fill="urlRef('lianIrisGrad')" />
                <ellipse cx="146" cy="115.5" rx="7.2" ry="4.5" fill="#ff9bc0" opacity="0.62" />
                <ellipse cx="146" cy="108.5" rx="4.4" ry="5.4" fill="#3b0c22" />
                <circle cx="141.5" cy="103.5" r="3.9" fill="#ffffff" />
                <circle cx="151.3" cy="114.2" r="2.0" fill="#ffffff" />
                <circle cx="150.4" cy="104.2" r="1.1" fill="#ffd9e8" />
              </g>
              <path d="M131 107 C136 93 156 93 161 107" fill="none" stroke="#4d1f33" stroke-width="4" stroke-linecap="round" />
              <path d="M157 107 L163.5 103.5" fill="none" stroke="#4d1f33" stroke-width="2.6" stroke-linecap="round" />
            </g>
          </template>

          <!-- Mouth (+ lip sync pulse when speaking) -->
          <g class="lian-mouth" style="transform-origin: 120px 132px">
            <template v-if="speaking && mood !== 'happy'">
              <ellipse cx="120" cy="132" rx="4.4" ry="3.8" fill="#d9587f" stroke="#6d233d" stroke-width="1.9" class="lian-mouth-talk" />
            </template>
            <template v-else-if="mood === 'happy'">
              <path d="M111 128 C114 139.5 126 139.5 129 128 Z" fill="#d44b74" stroke="#6d233d" stroke-width="2" stroke-linejoin="round" />
              <path d="M115 134 C118 132 122 132 125 134 C123 137.5 117 137.5 115 134 Z" fill="#ff9bb8" />
            </template>
            <template v-else-if="mood === 'thinking'">
              <ellipse cx="122" cy="132.5" rx="3.3" ry="4" fill="#d9587f" stroke="#6d233d" stroke-width="1.9" />
            </template>
            <template v-else-if="mood === 'comfort'">
              <path d="M114 131 Q120 137 126 131" fill="none" stroke="#8c3b55" stroke-width="2.3" stroke-linecap="round" />
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
            <path
              d="M73 74 C60 95 57 126 67 151 C73 144 76 130 76 112 Z"
              :fill="urlRef('lianHairMainGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
            <path
              d="M167 74 C180 95 183 126 173 151 C167 144 164 130 164 112 Z"
              :fill="urlRef('lianHairMainGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
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

        <!-- 7. Arms & State Props ON TOP of back hair -->
        <template v-if="mood === 'happy'">
          <g>
            <path
              d="M90 157 C74 155 56 144 51 128 C49 120 59 118 65 125 C72 135 79 144 90 150 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
            <path d="M52 130 Q59 135 66 130" fill="none" stroke="#fff7fa" stroke-width="3" stroke-linecap="round" />
            <circle cx="55" cy="121" r="7.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
          <g>
            <path
              d="M150 157 C166 155 184 144 189 128 C191 120 181 118 175 125 C168 135 161 144 150 150 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
            <path d="M174 130 Q181 135 188 130" fill="none" stroke="#fff7fa" stroke-width="3" stroke-linecap="round" />
            <circle cx="185" cy="121" r="7.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
        </template>

        <template v-else-if="mood === 'thinking'">
          <g>
            <path
              d="M90 158 C78 166 68 184 72 198 C74 206 83 204 86 196 C88 186 91 174 93 166 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
            <path d="M72 195 Q79 199 85 195" fill="none" stroke="#fff7fa" stroke-width="3.2" stroke-linecap="round" />
            <circle cx="77" cy="204" r="7.2" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
          <g>
            <path
              d="M150 158 C166 164 173 177 166 184 C159 190 144 178 135 159 L142 153 C149 165 155 170 158 172 C156 168 153 164 148 162 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
            <circle cx="136" cy="153" r="7.5" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
        </template>

        <template v-else-if="mood === 'comfort'">
          <g>
            <path
              d="M90 159 C76 168 78 189 98 191 L103 181 C89 180 88 172 94 165 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.4"
              stroke-linejoin="round"
            />
            <path
              d="M150 159 C164 168 162 189 142 191 L137 181 C151 180 152 172 146 165 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.4"
              stroke-linejoin="round"
            />
            <rect x="103" y="167" width="34" height="28" rx="8" fill="#fffaf8" stroke="#582c3e" stroke-width="2.3" />
            <path d="M137 174 C145 174 145 186 137 186" fill="none" stroke="#582c3e" stroke-width="2.3" stroke-linecap="round" />
            <ellipse cx="120" cy="170.5" rx="12.5" ry="3.2" fill="#9c5a43" />
            <path
              d="M114.5 179.5 C114.5 176.5 119 175.8 120 178.5 C121 175.8 125.5 176.5 125.5 179.5 C125.5 183 120 186.8 120 186.8 C120 186.8 114.5 183 114.5 179.5 Z"
              fill="#ff5c8f"
            />
            <circle cx="101.5" cy="184" r="6.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.2" />
            <circle cx="138.5" cy="184" r="6.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.2" />
            <g class="lian-steam-group">
              <path d="M113 161 C110 156 115 152 112 147" fill="none" stroke="#ffd8e4" stroke-width="2.4" stroke-linecap="round" />
              <path d="M126 161 C129 156 124 152 127 147" fill="none" stroke="#ffd8e4" stroke-width="2.4" stroke-linecap="round" />
            </g>
          </g>
        </template>

        <template v-else>
          <!-- Idle waving pose -->
          <g>
            <path
              d="M90 158 C78 164 67 183 70 198 C72 206 82 204 85 196 C88 186 91 174 93 166 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
            <path d="M70 195 Q77 199 84 195" fill="none" stroke="#fff7fa" stroke-width="3.2" stroke-linecap="round" />
            <circle cx="76" cy="204" r="7.2" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
          <g class="lian-wave-arm" style="transform-origin: 152px 154px">
            <path
              d="M150 158 C166 158 186 150 191 134 C193 126 183 123 177 130 C170 139 162 146 151 151 Z"
              :fill="urlRef('lianCardiganGrad')"
              stroke="#582c3e"
              stroke-width="2.5"
              stroke-linejoin="round"
            />
            <path d="M175 135 Q182 140 189 135" fill="none" stroke="#fff7fa" stroke-width="3" stroke-linecap="round" />
            <circle cx="187" cy="126" r="7.8" fill="#fff2ec" stroke="#582c3e" stroke-width="2.3" />
          </g>
        </template>
      </g>

      <!-- 8. Foreground Floating Accents -->
      <g v-if="mood === 'happy'" class="lian-happy-sparkles">
        <path
          d="M24 66 C24 59 34 57 36 64 C38 57 48 59 48 66 C48 74 36 82 36 82 C36 82 24 74 24 66 Z"
          fill="#ff5c93"
          stroke="#ffffff"
          stroke-width="1.8"
        />
        <path
          d="M196 50 C196 44 204 42 206 48 C208 42 216 44 216 50 C216 56 206 63 206 63 C206 63 196 56 196 50 Z"
          fill="#ff87b0"
          stroke="#ffffff"
          stroke-width="1.6"
        />
        <path
          d="M212 108 L215 115 L222 118 L215 121 L212 128 L209 121 L202 118 L209 115 Z"
          fill="#ffd866"
          stroke="#fff9df"
          stroke-width="1"
        />
        <path
          d="M24 106 L26.5 112 L32 114.5 L26.5 117 L24 123 L21.5 117 L16 114.5 L21.5 112 Z"
          fill="#ffd866"
          stroke="#fff9df"
          stroke-width="1"
        />
      </g>

      <g v-else-if="mood === 'thinking'" class="lian-think-bubble">
        <circle cx="187" cy="64" r="3.6" fill="#fff7fa" stroke="#f0729b" stroke-width="1.6" />
        <circle cx="195" cy="54" r="5.2" fill="#fff7fa" stroke="#f0729b" stroke-width="1.8" />
        <circle cx="211" cy="36" r="16" fill="#fff7fa" stroke="#e95c8c" stroke-width="2.2" />
        <text
          x="211"
          y="42.5"
          text-anchor="middle"
          font-family="PingFang SC, Arial, sans-serif"
          font-size="19"
          font-weight="800"
          fill="#d93f74"
        >
          ?
        </text>
        <path
          d="M28 70 L31 77 L38 80 L31 83 L28 90 L25 83 L18 80 L25 77 Z"
          fill="#ffd866"
          stroke="#fff9df"
          stroke-width="1"
        />
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

.lian-body-float {
  animation: lian-float 3.2s ease-in-out infinite;
}

.mood-happy .lian-body-float {
  animation: lian-happy-hop 0.9s ease-in-out infinite;
}

.mood-thinking .lian-body-float {
  animation: lian-think-sway 2.8s ease-in-out infinite;
}

.is-bouncing .lian-body-float {
  animation: lian-jelly 0.56s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}

.lian-tail-group {
  animation: lian-tail-wag 2.6s ease-in-out infinite;
}

.mood-happy .lian-tail-group {
  animation: lian-tail-wag 0.68s ease-in-out infinite;
}

.lian-ear-left {
  animation: lian-ear-twitch 5.4s ease-in-out infinite;
}

.lian-ear-right {
  animation: lian-ear-twitch 5.4s ease-in-out 0.25s infinite;
}

.lian-wave-arm {
  animation: lian-hand-wave 3.4s ease-in-out infinite;
}

.lian-mouth-talk {
  animation: lian-talk-pulse 0.26s ease-in-out infinite alternate;
}

.lian-think-bubble {
  animation: lian-think-pulse 1.6s ease-in-out infinite;
}

.lian-happy-sparkles {
  animation: lian-sparkle-pop 1.1s ease-in-out infinite alternate;
}

.lian-steam-group {
  animation: lian-steam-rise 2.2s ease-in-out infinite;
}

.lian-aura-pulse {
  animation: lian-aura-glow 2.4s ease-in-out infinite;
}

@keyframes lian-float {
  0%,
  100% {
    transform: translateY(0px);
  }
  50% {
    transform: translateY(-4.5px);
  }
}

@keyframes lian-happy-hop {
  0%,
  100% {
    transform: translateY(0px) scale(1);
  }
  45% {
    transform: translateY(-7px) scale(1.02, 0.98);
  }
}

@keyframes lian-think-sway {
  0%,
  100% {
    transform: translateY(0px) rotate(0deg);
  }
  50% {
    transform: translateY(-3px) rotate(1.5deg);
  }
}

@keyframes lian-jelly {
  0% {
    transform: scale(1, 1);
  }
  25% {
    transform: scale(1.12, 0.88) translateY(4px);
  }
  55% {
    transform: scale(0.93, 1.09) translateY(-8px);
  }
  80% {
    transform: scale(1.03, 0.97) translateY(0px);
  }
  100% {
    transform: scale(1, 1);
  }
}

@keyframes lian-tail-wag {
  0%,
  100% {
    transform: rotate(-4deg);
  }
  50% {
    transform: rotate(7deg);
  }
}

@keyframes lian-ear-twitch {
  0%,
  84%,
  100% {
    transform: rotate(0deg);
  }
  88% {
    transform: rotate(-7deg);
  }
  92% {
    transform: rotate(3deg);
  }
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

@keyframes lian-talk-pulse {
  0% {
    transform: scale(1, 0.55);
  }
  100% {
    transform: scale(1.08, 1.15);
  }
}

@keyframes lian-think-pulse {
  0%,
  100% {
    transform: translateY(0px) scale(1);
  }
  50% {
    transform: translateY(-3px) scale(1.05);
  }
}

@keyframes lian-sparkle-pop {
  0% {
    opacity: 0.78;
    transform: scale(0.96);
  }
  100% {
    opacity: 1;
    transform: scale(1.05);
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
    transform: translateY(-3px);
  }
}

@keyframes lian-aura-glow {
  0%,
  100% {
    opacity: 0.55;
  }
  50% {
    opacity: 0.92;
  }
}
</style>
