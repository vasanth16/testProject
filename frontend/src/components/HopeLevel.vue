<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: {
    type: Number,
    default: null,
  },
})

const levels = [
  { min: 90, label: 'Radiant', color: 'bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300', barColor: 'bg-amber-400', icon: '✦', tier: 5 },
  { min: 80, label: 'Inspiring', color: 'bg-rose-100 dark:bg-rose-900/50 text-rose-700 dark:text-rose-300', barColor: 'bg-rose-400', icon: '♥', tier: 4 },
  { min: 70, label: 'Uplifting', color: 'bg-sky-100 dark:bg-sky-900/50 text-sky-700 dark:text-sky-300', barColor: 'bg-sky-400', icon: '↑', tier: 3 },
  { min: 60, label: 'Hopeful', color: 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300', barColor: 'bg-emerald-400', icon: '✓', tier: 2 },
  { min: 50, label: 'Encouraging', color: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400', barColor: 'bg-slate-400', icon: '○', tier: 1 },
]

const level = computed(() => {
  if (props.score === null) return null
  return levels.find((l) => props.score >= l.min) || levels[levels.length - 1]
})

const barWidth = computed(() => {
  if (!level.value) return '0%'
  return `${(level.value.tier / 5) * 100}%`
})
</script>

<template>
  <span
    v-if="level"
    :class="[level.color, 'inline-flex flex-col px-1.5 py-0.5 text-[10px] font-medium rounded']"
    :title="`Hope score: ${score}`"
  >
    <span class="inline-flex items-center gap-0.5">
      <span class="opacity-70">{{ level.icon }}</span>
      {{ level.label }}
    </span>
    <span class="mt-0.5 h-[2px] w-full bg-black/10 dark:bg-white/10 rounded-full overflow-hidden">
      <span
        :class="[level.barColor, 'block h-full rounded-full transition-all']"
        :style="{ width: barWidth }"
      />
    </span>
  </span>
</template>
