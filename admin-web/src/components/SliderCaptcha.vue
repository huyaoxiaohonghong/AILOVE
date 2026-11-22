<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  createSliderCaptcha,
  verifySliderCaptcha,
  type CaptchaScene,
  type SliderChallenge,
  type TrailPoint,
} from '@/api/auth'

const props = defineProps<{
  scene: CaptchaScene
}>()

const emit = defineEmits<{
  verified: [payload: { token: string; humanScore: number }]
  invalidated: []
}>()

const loading = ref(false)
const verifying = ref(false)
const challenge = ref<SliderChallenge | null>(null)
const status = ref<'idle' | 'dragging' | 'success' | 'error'>('idle')
const statusMessage = ref('按住滑块向右拖动，拼合缺口')
const humanScore = ref<number | null>(null)

const sliderX = ref(0)
const trackWidth = computed(() => challenge.value?.canvas_width ?? 320)
const pieceSize = computed(() => challenge.value?.piece_size ?? 56)
const maxSlideX = computed(() => Math.max(0, trackWidth.value - pieceSize.value))

const thumbWidth = 46
const thumbLeft = computed(() => {
  if (maxSlideX.value <= 0) return 0
  const maxThumb = trackWidth.value - thumbWidth
  return (sliderX.value / maxSlideX.value) * maxThumb
})

let dragging = false
let startClientX = 0
let startClientY = 0
let startTime = 0
let trail: TrailPoint[] = []
let autoResetTimer: number | null = null

function clearTimer() {
  if (autoResetTimer !== null) {
    window.clearTimeout(autoResetTimer)
    autoResetTimer = null
  }
}

async function loadChallenge() {
  clearTimer()
  loading.value = true
  status.value = 'idle'
  sliderX.value = 0
  humanScore.value = null
  statusMessage.value = '按住滑块向右拖动，拼合缺口'
  emit('invalidated')
  try {
    challenge.value = await createSliderCaptcha(props.scene)
  } finally {
    loading.value = false
  }
}

function onPointerDown(e: PointerEvent) {
  if (loading.value || verifying.value || status.value === 'success' || !challenge.value) return
  e.preventDefault()
  clearTimer()
  dragging = true
  status.value = 'dragging'
  statusMessage.value = '对准缺口后松开滑块'
  startClientX = e.clientX
  startClientY = e.clientY
  startTime = performance.now()
  sliderX.value = 0
  trail = [{ x: 0, y: 0, t: 0 }]

  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerUp)
}

function onPointerMove(e: PointerEvent) {
  if (!dragging) return
  const rawDx = e.clientX - startClientX
  const maxThumb = Math.max(1, trackWidth.value - thumbWidth)
  const clampedThumb = Math.max(0, Math.min(maxThumb, rawDx))
  const mappedX = (clampedThumb / maxThumb) * maxSlideX.value
  const dy = e.clientY - startClientY
  const elapsed = performance.now() - startTime

  sliderX.value = mappedX
  trail.push({
    x: Number(mappedX.toFixed(2)),
    y: Number(dy.toFixed(2)),
    t: Number(elapsed.toFixed(2)),
  })
}

async function onPointerUp() {
  if (!dragging) return
  dragging = false
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)

  if (!challenge.value) return
  const durationMs = Number((performance.now() - startTime).toFixed(2))
  const finalX = Number(sliderX.value.toFixed(2))

  if (finalX < 12) {
    sliderX.value = 0
    status.value = 'idle'
    statusMessage.value = '按住滑块向右拖动，拼合缺口'
    return
  }

  const last = trail[trail.length - 1]
  if (!last || durationMs - last.t >= 4) {
    trail.push({
      x: finalX,
      y: last ? last.y : 0,
      t: durationMs,
    })
  }

  verifying.value = true
  statusMessage.value = '正在校验行为轨迹...'
  try {
    const res = await verifySliderCaptcha({
      captcha_id: challenge.value.captcha_id,
      scene: props.scene,
      final_x: finalX,
      duration_ms: durationMs,
      trail,
    })
    humanScore.value = res.human_score

    if (res.passed && res.captcha_token) {
      status.value = 'success'
      statusMessage.value = `验证通过 · 行为评分 ${res.human_score} 分`
      emit('verified', { token: res.captcha_token, humanScore: res.human_score })
    } else {
      status.value = 'error'
      statusMessage.value = res.reason || '验证失败，请重试'
      emit('invalidated')
      autoResetTimer = window.setTimeout(() => {
        void loadChallenge()
      }, 950)
    }
  } catch {
    status.value = 'error'
    statusMessage.value = '校验异常，正在刷新拼图'
    emit('invalidated')
    autoResetTimer = window.setTimeout(() => {
      void loadChallenge()
    }, 950)
  } finally {
    verifying.value = false
  }
}

watch(
  () => props.scene,
  () => {
    void loadChallenge()
  },
)

onMounted(() => {
  void loadChallenge()
})

onBeforeUnmount(() => {
  clearTimer()
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
})

defineExpose({
  reset: loadChallenge,
})
</script>

<template>
  <div class="slider-captcha" :class="[`is-${status}`]">
    <div
      class="canvas-box"
      :style="{
        width: `${trackWidth}px`,
        height: `${challenge?.canvas_height ?? 160}px`,
      }"
    >
      <template v-if="challenge">
        <img :src="challenge.bg_image" alt="拼图背景" class="bg-img" draggable="false" />
        <img
          :src="challenge.piece_image"
          alt="拼图滑块"
          class="piece-img"
          draggable="false"
          :style="{
            top: `${challenge.piece_y}px`,
            left: `${sliderX}px`,
            width: `${challenge.piece_size}px`,
            height: `${challenge.piece_size}px`,
          }"
        />
      </template>
      <div v-if="loading" class="canvas-mask">正在生成动态拼图...</div>
      <button
        type="button"
        class="refresh-btn"
        title="换一张拼图"
        :disabled="loading || verifying"
        @click="loadChallenge"
      >
        <el-icon><Refresh /></el-icon>
      </button>
    </div>

    <div class="track" :style="{ width: `${trackWidth}px` }">
      <div class="track-fill" :style="{ width: `${thumbLeft + thumbWidth / 2}px` }" />
      <span class="track-text">{{ statusMessage }}</span>
      <div
        class="track-thumb"
        :style="{ left: `${thumbLeft}px`, width: `${thumbWidth}px` }"
        @pointerdown="onPointerDown"
      >
        <el-icon v-if="status === 'success'"><Check /></el-icon>
        <el-icon v-else-if="status === 'error'"><Close /></el-icon>
        <el-icon v-else><Right /></el-icon>
      </div>
    </div>
  </div>
</template>

<style scoped>
.slider-captcha {
  user-select: none;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.canvas-box {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  background: var(--ailove-canvas);
  border: 1px solid var(--ailove-border-strong);
  box-shadow: inset 0 1px 4px rgba(26, 22, 29, 0.08);
}

.bg-img {
  display: block;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.piece-img {
  position: absolute;
  pointer-events: none;
  filter: drop-shadow(0 4px 8px rgba(26, 22, 29, 0.45));
  will-change: left;
}

.canvas-mask {
  position: absolute;
  inset: 0;
  background: rgba(251, 249, 247, 0.86);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--ailove-ink-secondary);
}

.refresh-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 30px;
  height: 30px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  background: rgba(26, 22, 29, 0.52);
  backdrop-filter: blur(6px);
  color: #ffffff;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.16s var(--ailove-ease), background 0.16s;
}

.refresh-btn:hover {
  background: rgba(26, 22, 29, 0.78);
  transform: rotate(30deg);
}

.track {
  position: relative;
  height: 44px;
  border-radius: 12px;
  background: var(--ailove-subtle);
  border: 1px solid var(--ailove-border-strong);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  touch-action: none;
}

.track-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: linear-gradient(90deg, rgba(225, 75, 104, 0.16), rgba(200, 53, 83, 0.24));
  transition: background 0.16s;
}

.track-text {
  position: relative;
  z-index: 1;
  font-size: 12.5px;
  color: var(--ailove-ink-secondary);
  padding: 0 50px;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.track-thumb {
  position: absolute;
  top: 2px;
  bottom: 2px;
  z-index: 2;
  background: #ffffff;
  border: 1px solid var(--ailove-brand-200);
  border-radius: 10px;
  box-shadow: 0 3px 10px rgba(26, 22, 29, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ailove-brand-600);
  cursor: grab;
  font-size: 16px;
  transition: background 0.16s, color 0.16s, border-color 0.16s;
}

.track-thumb:hover {
  border-color: var(--ailove-brand-500);
}

.track-thumb:active {
  cursor: grabbing;
  background: var(--ailove-brand-600);
  border-color: var(--ailove-brand-600);
  color: #ffffff;
}

.is-success .track {
  border-color: var(--ailove-success-border);
  background: var(--ailove-success-bg);
}

.is-success .track-fill {
  background: rgba(13, 138, 103, 0.18);
}

.is-success .track-text {
  color: var(--ailove-success);
  font-weight: 600;
}

.is-success .track-thumb {
  background: var(--ailove-success);
  border-color: var(--ailove-success);
  color: #ffffff;
  cursor: default;
}

.is-error .track {
  border-color: var(--ailove-danger-border);
  background: var(--ailove-danger-bg);
  animation: shake 0.36s ease-in-out;
}

.is-error .track-fill {
  background: rgba(190, 18, 60, 0.18);
}

.is-error .track-text {
  color: var(--ailove-danger);
  font-weight: 500;
}

.is-error .track-thumb {
  background: var(--ailove-danger);
  border-color: var(--ailove-danger);
  color: #ffffff;
}

@keyframes shake {
  0%,
  100% {
    transform: translateX(0);
  }
  25% {
    transform: translateX(-6px);
  }
  50% {
    transform: translateX(6px);
  }
  75% {
    transform: translateX(-4px);
  }
}
</style>
