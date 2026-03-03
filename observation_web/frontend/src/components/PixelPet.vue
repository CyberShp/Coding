<template>
  <div
    class="pixel-pet"
    :class="`mood-${mood}`"
    :style="petStyle"
  >
    <svg
      viewBox="0 0 64 64"
      class="pet-svg"
      xmlns="http://www.w3.org/2000/svg"
    >
      <!-- Body -->
      <rect x="20" y="36" width="24" height="20" fill="#e8b86d" stroke="#c4a060" stroke-width="1" />
      <!-- Belly -->
      <rect x="24" y="44" width="16" height="8" fill="#f5d9a0" />
      <!-- Head -->
      <g :transform="`translate(32, 32) rotate(${headRotation}) translate(-32, -32)`">
        <rect x="28" y="16" width="24" height="20" fill="#e8b86d" stroke="#c4a060" stroke-width="1" />
        <!-- Eyes -->
        <g :transform="`translate(32, 26) translate(${eyeOffsetX}, ${eyeOffsetY}) translate(-32, -26)`">
          <rect x="24" y="22" width="6" height="6" :fill="eyeColor" fill-opacity="0.9" />
          <rect x="34" y="22" width="6" height="6" :fill="eyeColor" fill-opacity="0.9" />
          <!-- Pupils -->
          <rect v-if="mood !== 'hiding'" :x="24 + pupilX" :y="22 + pupilY" width="2" height="2" fill="#1a1a1a" />
          <rect v-if="mood !== 'hiding'" :x="34 + pupilX" :y="22 + pupilY" width="2" height="2" fill="#1a1a1a" />
        </g>
        <!-- Hands/Arms -->
        <rect
          v-if="mood === 'hiding'"
          x="20"
          y="20"
          width="28"
          height="12"
          fill="#e8b86d"
          rx="2"
          class="covering-eyes"
        />
        <g v-else-if="mood === 'success'" class="arms-up">
          <rect x="22" y="18" width="6" height="8" fill="#e8b86d" transform="rotate(-45 25 22)" />
          <rect x="36" y="18" width="6" height="8" fill="#e8b86d" transform="rotate(45 39 22)" />
        </g>
      </g>
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  mood: {
    type: String,
    default: 'idle',
    validator: (v) => ['idle', 'watching', 'hiding', 'error', 'success'].includes(v),
  },
  lookAt: {
    type: Object,
    default: () => ({ x: 0, y: 0 }),
  },
  offset: {
    type: Number,
    default: 0,
  },
})

const headRotation = computed(() => {
  if (props.mood === 'hiding') return -15
  if (props.mood === 'error') return 5
  const dx = props.lookAt.x - 0.5
  return Math.max(-20, Math.min(20, dx * 30))
})

const eyeOffsetX = computed(() => {
  if (props.mood === 'hiding') return 0
  const dx = props.lookAt.x - 0.5
  return Math.max(-3, Math.min(3, dx * 8))
})

const eyeOffsetY = computed(() => {
  if (props.mood === 'hiding') return 0
  const dy = props.lookAt.y - 0.5
  return Math.max(-2, Math.min(2, dy * 6))
})

const pupilX = computed(() => Math.max(-1, Math.min(1, (props.lookAt.x - 0.5) * 4)))
const pupilY = computed(() => Math.max(-1, Math.min(1, (props.lookAt.y - 0.5) * 4)))

const eyeColor = computed(() => {
  if (props.mood === 'error') return '#ff4444'
  return '#2d2d2d'
})

const petStyle = computed(() => ({
  '--bounce': props.mood === 'success' ? '0.5s' : '0',
  '--shake': props.mood === 'error' ? '0.4s' : '0',
  '--y-offset': `${props.offset * 8}px`,
}))
</script>

<style scoped>
.pixel-pet {
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  transition: transform 0.15s ease-out;
}

.pet-svg {
  width: 80px;
  height: 80px;
  display: block;
}

.mood-success {
  animation: bounce 0.5s ease-in-out 2;
}

.mood-error {
  animation: shake 0.4s ease-in-out 2;
}

@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-12px); }
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-4px); }
  75% { transform: translateX(4px); }
}
</style>
