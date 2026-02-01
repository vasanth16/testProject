<script setup>
import { ref, onMounted } from 'vue'
import { inject } from '@vercel/analytics'
import AppHeader from './components/AppHeader.vue'
import FilterBar from './components/FilterBar.vue'
import ArticleFeed from './components/ArticleFeed.vue'
import InstallPrompt from './components/InstallPrompt.vue'
import OfflineIndicator from './components/OfflineIndicator.vue'
import { getCategories, getRegions } from './services/api.js'
import { useArticles } from './composables/useArticles.js'

const { filters, setFilter } = useArticles()

const categories = ref([])
const regions = ref([])

async function fetchFilters() {
  try {
    const [cats, regs] = await Promise.all([
      getCategories(),
      getRegions(),
    ])
    categories.value = cats
    regions.value = regs
  } catch (e) {
    // Silently fail - filters just won't show
  }
}

function handleFilterChange({ type, value }) {
  setFilter(type, value)
}

onMounted(() => {
  fetchFilters()
  // Initialize Vercel Analytics
  inject()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950 pb-20 transition-colors">
    <OfflineIndicator />
    <AppHeader />

    <main class="container mx-auto px-4 py-4 max-w-5xl">
      <FilterBar
        :categories="categories"
        :regions="regions"
        :active-category="filters.category"
        :active-region="filters.region"
        :active-min-score="filters.minScore"
        @filter-change="handleFilterChange"
      />

      <ArticleFeed />
    </main>

    <InstallPrompt />
  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html {
  scroll-behavior: smooth;
}

body {
  font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
</style>
