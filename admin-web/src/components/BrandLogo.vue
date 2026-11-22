<script setup lang="ts">
withDefaults(
  defineProps<{
    size?: number
  }>(),
  {
    size: 36,
  },
)
</script>

<template>
  <div
    class="brand-mark"
    :style="{ width: `${size}px`, height: `${size}px`, borderRadius: `${Math.round(size * 0.28)}px` }"
    aria-hidden="true"
  >
    <svg viewBox="0 0 36 36" fill="none" xmlns="http://www.w3.org/2000/svg" class="brand-svg">
      <!-- Heart-Spark Emblem: Warmth (Heart) + Intelligence (4-Point Spark) -->
      <path
        d="M18 28.4C17.6 28.4 17.2 28.25 16.9 27.98C11.2 22.9 7.2 19.25 7.2 14.35C7.2 10.6 10.1 7.8 13.7 7.8C15.65 7.8 17.18 8.65 18 9.95C18.82 8.65 20.35 7.8 22.3 7.8C25.9 7.8 28.8 10.6 28.8 14.35C28.8 19.25 24.8 22.9 19.1 27.98C18.8 28.25 18.4 28.4 18 28.4Z"
        fill="rgba(255,255,255,0.22)"
        stroke="white"
        stroke-width="1.8"
        stroke-linejoin="round"
      />
      <path
        d="M18 11.8L19.15 15.25L22.6 16.4L19.15 17.55L18 21L16.85 17.55L13.4 16.4L16.85 15.25L18 11.8Z"
        fill="white"
      />
    </svg>
  </div>
</template>

<style scoped>
.brand-mark {
  background: linear-gradient(135deg, #e14b68 0%, #c83553 58%, #d97706 135%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 6px 16px -4px rgba(200, 53, 83, 0.45);
}

.brand-svg {
  width: 78%;
  height: 78%;
}
</style>
