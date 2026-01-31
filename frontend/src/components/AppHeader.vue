<script setup>
import { ref, onMounted } from 'vue'
import { SunIcon, MoonIcon } from '@heroicons/vue/24/outline'
import { getStats } from '../services/api.js'

const todayCount = ref(null)

// Dark mode - inline for debugging
const isDark = ref(false)

onMounted(() => {
  // Sync with current DOM state
  isDark.value = document.documentElement.classList.contains('dark')
  fetchStats()
})

function toggle() {
  isDark.value = !isDark.value
  if (isDark.value) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
  localStorage.setItem('darkMode', isDark.value ? 'true' : 'false')
}

async function fetchStats() {
  try {
    const stats = await getStats()
    todayCount.value = stats.articles?.fetched_today ?? null
  } catch (e) {
    // Silently fail
  }
}
</script>

<template>
  <header class="bg-white dark:bg-gray-900 border-b border-gray-100 dark:border-gray-800 sticky top-0 z-20 backdrop-blur-sm bg-white/95 dark:bg-gray-900/95">
    <div class="container mx-auto px-4">
      <div class="flex items-center justify-between h-14">
        <!-- Logo & Title -->
        <div class="flex items-center gap-2.5">
          <img src="/icons/icon.svg" alt="Logo" class="w-8 h-8 rounded-lg" />
          <h1 class="text-base font-semibold text-gray-900 dark:text-white leading-tight">
            Hopeful News
          </h1>
        </div>

        <!-- Right side -->
        <div class="flex items-center gap-2">
          <span
            v-if="todayCount !== null"
            class="text-[10px] text-primary-600 dark:text-primary-400 bg-primary-50 dark:bg-primary-900/50 px-2 py-1 rounded-full font-medium"
          >
            {{ todayCount }} new today
          </span>

          <!-- Dark mode toggle -->
          <button
            @click="toggle"
            class="p-2 rounded-lg text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
          >
            <MoonIcon v-if="!isDark" class="w-5 h-5" />
            <SunIcon v-else class="w-5 h-5" />
          </button>
        </div>
      </div>
    </div>
  </header>
</template>
