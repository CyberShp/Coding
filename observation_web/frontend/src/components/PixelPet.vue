<template>
  <div class="blob-mascot" :class="`mood-${mood}`">
    <!-- Orange Blob - big friendly round one -->
    <svg v-if="character === 'orange'" viewBox="0 0 200 170" class="mascot-svg">
      <ellipse cx="100" cy="115" rx="90" ry="55" fill="#E8734A" />
      <ellipse cx="80" cy="105" rx="35" ry="22" fill="#ED8D66" opacity="0.45" />
      <g v-if="mood !== 'hiding'">
        <circle :cx="78 + eyeX" :cy="102 + eyeY" r="6" fill="#2D2D2D" />
        <circle :cx="122 + eyeX" :cy="102 + eyeY" r="6" fill="#2D2D2D" />
        <circle :cx="76 + eyeX * 0.4" :cy="100 + eyeY * 0.4" r="2" fill="white" opacity="0.7" />
        <circle :cx="120 + eyeX * 0.4" :cy="100 + eyeY * 0.4" r="2" fill="white" opacity="0.7" />
      </g>
      <g v-else>
        <ellipse cx="100" cy="105" rx="42" ry="10" fill="#D4623A" />
      </g>
      <g v-if="mood === 'success'" class="arms-cheer">
        <ellipse cx="30" cy="100" rx="12" ry="8" fill="#D4623A" transform="rotate(-30 30 100)" />
        <ellipse cx="170" cy="100" rx="12" ry="8" fill="#D4623A" transform="rotate(30 170 100)" />
      </g>
    </svg>

    <!-- Purple Monster - tall quirky one -->
    <svg v-else-if="character === 'purple'" viewBox="0 0 120 220" class="mascot-svg">
      <rect x="20" y="18" width="22" height="32" rx="11" fill="#6C5CE7" />
      <rect x="78" y="18" width="22" height="32" rx="11" fill="#6C5CE7" />
      <rect x="15" y="40" width="90" height="150" rx="32" fill="#6C5CE7" />
      <rect x="28" y="55" width="30" height="40" rx="12" fill="#7E6FEE" opacity="0.35" />
      <g v-if="mood !== 'hiding'">
        <rect :x="33 + eyeX" :y="98 + eyeY" width="13" height="13" rx="3" fill="#FFE066" />
        <rect :x="72 + eyeX" :y="98 + eyeY" width="13" height="13" rx="3" fill="#FFE066" />
        <rect :x="37 + pupilX" :y="102 + pupilY" width="5" height="5" rx="1" fill="#3D3270" />
        <rect :x="76 + pupilX" :y="102 + pupilY" width="5" height="5" rx="1" fill="#3D3270" />
      </g>
      <g v-else>
        <rect x="25" y="94" width="70" height="22" rx="8" fill="#5A4BD6" />
      </g>
      <ellipse cx="38" cy="192" rx="14" ry="7" fill="#5A4BD6" />
      <ellipse cx="82" cy="192" rx="14" ry="7" fill="#5A4BD6" />
      <g v-if="mood === 'success'" class="arms-cheer">
        <rect x="0" y="75" width="18" height="10" rx="5" fill="#5A4BD6" transform="rotate(-40 9 80)" />
        <rect x="102" y="75" width="18" height="10" rx="5" fill="#5A4BD6" transform="rotate(40 111 80)" />
      </g>
    </svg>

    <!-- Yellow Duck - cute bird shape -->
    <svg v-else-if="character === 'yellow'" viewBox="0 0 140 170" class="mascot-svg">
      <path
        d="M70 28 C95 28 118 50 118 85 C118 130 100 155 65 155 C30 155 15 125 15 90 C15 50 40 28 70 28Z"
        fill="#FDCB6E"
      />
      <ellipse cx="50" cy="75" rx="22" ry="18" fill="#FDE28E" opacity="0.4" />
      <ellipse cx="112" cy="62" rx="15" ry="7" fill="#E8734A" />
      <g v-if="mood !== 'hiding'">
        <circle :cx="82 + eyeX" :cy="65 + eyeY" r="5" fill="#2D2D2D" />
        <circle :cx="80.5 + eyeX * 0.4" :cy="63.5 + eyeY * 0.4" r="1.8" fill="white" opacity="0.7" />
      </g>
      <g v-else>
        <ellipse cx="82" cy="67" rx="16" ry="7" fill="#E5B84C" />
      </g>
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  character: {
    type: String,
    default: 'orange',
    validator: (v) => ['orange', 'purple', 'yellow'].includes(v),
  },
  mood: {
    type: String,
    default: 'idle',
    validator: (v) => ['idle', 'watching', 'hiding', 'error', 'success'].includes(v),
  },
  lookAt: {
    type: Object,
    default: () => ({ x: 0.5, y: 0.5 }),
  },
})

const eyeX = computed(() => {
  if (props.mood === 'hiding') return 0
  return Math.max(-4, Math.min(4, (props.lookAt.x - 0.5) * 12))
})

const eyeY = computed(() => {
  if (props.mood === 'hiding') return 0
  return Math.max(-3, Math.min(3, (props.lookAt.y - 0.5) * 8))
})

const pupilX = computed(() => Math.max(-2, Math.min(2, (props.lookAt.x - 0.5) * 6)))
const pupilY = computed(() => Math.max(-2, Math.min(2, (props.lookAt.y - 0.5) * 6)))
</script>

<style scoped>
.blob-mascot {
  transition: transform 0.2s ease-out;
  will-change: transform;
}

.mascot-svg {
  display: block;
  width: 100%;
  height: 100%;
}

.mood-success {
  animation: blob-bounce 0.5s ease-in-out 3;
}

.mood-error {
  animation: blob-shake 0.4s ease-in-out 2;
}

@keyframes blob-bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-14px); }
}

@keyframes blob-shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-6px); }
  75% { transform: translateX(6px); }
}
</style>
