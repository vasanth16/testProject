<script setup>
import { computed } from 'vue'

const props = defineProps({
  categories: {
    type: Array,
    default: () => [],
  },
  regions: {
    type: Array,
    default: () => [],
  },
  activeCategory: {
    type: String,
    default: null,
  },
  activeRegion: {
    type: String,
    default: null,
  },
  activeMinScore: {
    type: Number,
    default: null,
  },
})

const emit = defineEmits(['filter-change'])

const categoryColors = {
  environment: 'bg-teal-100 dark:bg-teal-900/50 text-teal-700 dark:text-teal-300 hover:bg-teal-200 dark:hover:bg-teal-900/70',
  health: 'bg-pink-100 dark:bg-pink-900/50 text-pink-700 dark:text-pink-300 hover:bg-pink-200 dark:hover:bg-pink-900/70',
  technology: 'bg-indigo-100 dark:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 hover:bg-indigo-200 dark:hover:bg-indigo-900/70',
  social: 'bg-violet-100 dark:bg-violet-900/50 text-violet-700 dark:text-violet-300 hover:bg-violet-200 dark:hover:bg-violet-900/70',
  humanitarian: 'bg-lime-100 dark:bg-lime-900/50 text-lime-700 dark:text-lime-300 hover:bg-lime-200 dark:hover:bg-lime-900/70',
  general: 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700',
}

const categoryActiveColors = {
  environment: 'bg-teal-500 dark:bg-teal-600 text-white',
  health: 'bg-pink-500 dark:bg-pink-600 text-white',
  technology: 'bg-indigo-500 dark:bg-indigo-600 text-white',
  social: 'bg-violet-500 dark:bg-violet-600 text-white',
  humanitarian: 'bg-lime-500 dark:bg-lime-600 text-white',
  general: 'bg-gray-500 dark:bg-gray-600 text-white',
}

function getCategoryColor(name, isActive) {
  const key = name?.toLowerCase() || 'general'
  if (isActive) {
    return categoryActiveColors[key] || categoryActiveColors.general
  }
  return categoryColors[key] || categoryColors.general
}

function selectCategory(value) {
  emit('filter-change', { type: 'category', value })
}

function selectRegion(value) {
  emit('filter-change', { type: 'region', value })
}

function selectMinScore(value) {
  emit('filter-change', { type: 'minScore', value })
}

const ratingLevels = [
  { min: 90, label: 'Radiant', color: 'bg-amber-100 dark:bg-amber-900/50 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/70', activeColor: 'bg-amber-500 dark:bg-amber-600 text-white' },
  { min: 80, label: 'Inspiring', color: 'bg-rose-100 dark:bg-rose-900/50 text-rose-700 dark:text-rose-300 hover:bg-rose-200 dark:hover:bg-rose-900/70', activeColor: 'bg-rose-500 dark:bg-rose-600 text-white' },
  { min: 70, label: 'Uplifting', color: 'bg-sky-100 dark:bg-sky-900/50 text-sky-700 dark:text-sky-300 hover:bg-sky-200 dark:hover:bg-sky-900/70', activeColor: 'bg-sky-500 dark:bg-sky-600 text-white' },
  { min: 60, label: 'Hopeful', color: 'bg-emerald-100 dark:bg-emerald-900/50 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-200 dark:hover:bg-emerald-900/70', activeColor: 'bg-emerald-500 dark:bg-emerald-600 text-white' },
]

const hasFilters = computed(() => props.categories.length > 0 || props.regions.length > 0)
const hasActiveFilter = computed(() => props.activeCategory || props.activeRegion || props.activeMinScore)
</script>

<template>
  <div v-if="hasFilters" class="mb-4">
    <div class="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-hide">
      <!-- Categories -->
      <template v-if="categories.length > 0">
        <span class="text-[10px] text-gray-400 dark:text-gray-500 uppercase tracking-wide shrink-0">Category</span>

        <button
          @click="selectCategory(null)"
          :class="[
            'px-2.5 py-1 text-xs font-medium rounded-full transition-colors shrink-0',
            !activeCategory
              ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
          ]"
        >
          All
        </button>

        <button
          v-for="cat in categories"
          :key="cat.name"
          @click="selectCategory(cat.name)"
          :class="[
            'px-2.5 py-1 text-xs font-medium rounded-full transition-colors shrink-0',
            getCategoryColor(cat.name, activeCategory === cat.name)
          ]"
        >
          {{ cat.name }}
          <span class="opacity-60 ml-1">{{ cat.count }}</span>
        </button>

        <span class="text-gray-300 dark:text-gray-700 shrink-0">|</span>
      </template>

      <!-- Rating Levels -->
      <span class="text-[10px] text-gray-400 dark:text-gray-500 uppercase tracking-wide shrink-0">Level</span>

      <button
        @click="selectMinScore(null)"
        :class="[
          'px-2.5 py-1 text-xs font-medium rounded-full transition-colors shrink-0',
          !activeMinScore
            ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
            : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
        ]"
      >
        All
      </button>

      <button
        v-for="level in ratingLevels"
        :key="level.min"
        @click="selectMinScore(level.min)"
        :class="[
          'px-2.5 py-1 text-xs font-medium rounded-full transition-colors shrink-0',
          activeMinScore === level.min ? level.activeColor : level.color
        ]"
      >
        {{ level.label }}+
      </button>

      <!-- Regions -->
      <template v-if="regions.length > 0">
        <span class="text-gray-300 dark:text-gray-700 shrink-0">|</span>
        <span class="text-[10px] text-gray-400 dark:text-gray-500 uppercase tracking-wide shrink-0">Region</span>

        <button
          @click="selectRegion(null)"
          :class="[
            'px-2.5 py-1 text-xs font-medium rounded-full transition-colors shrink-0',
            !activeRegion
              ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
          ]"
        >
          All
        </button>

        <button
          v-for="region in regions"
          :key="region.name"
          @click="selectRegion(region.name)"
          :class="[
            'px-2.5 py-1 text-xs font-medium rounded-full transition-colors shrink-0',
            activeRegion === region.name
              ? 'bg-gray-800 dark:bg-gray-200 text-white dark:text-gray-900'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
          ]"
        >
          {{ region.name }}
          <span class="opacity-60 ml-1">{{ region.count }}</span>
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
</style>
