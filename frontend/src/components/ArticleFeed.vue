<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useArticles } from '../composables/useArticles.js'
import ArticleCard from './ArticleCard.vue'
import ArticleCardSkeleton from './ArticleCardSkeleton.vue'
import LoadingSpinner from './LoadingSpinner.vue'
import ErrorMessage from './ErrorMessage.vue'

const {
  articles,
  loading,
  error,
  hasMore,
  total,
  fetchArticles,
  loadMore,
} = useArticles()

// Pull-to-refresh state
const pullDistance = ref(0)
const isPulling = ref(false)
const isRefreshing = ref(false)
const startY = ref(0)
const feedContainer = ref(null)

const PULL_THRESHOLD = 80
const MAX_PULL = 120
const isTouchDevice = ref(false)

const pullProgress = computed(() => Math.min(pullDistance.value / PULL_THRESHOLD, 1))
const showPullIndicator = computed(() => isPulling.value || isRefreshing.value)

function onTouchStart(e) {
  if (isRefreshing.value || window.scrollY > 0) return
  startY.value = e.touches[0].clientY
  isPulling.value = true
}

function onTouchMove(e) {
  if (!isPulling.value || isRefreshing.value) return

  const currentY = e.touches[0].clientY
  const diff = currentY - startY.value

  if (diff > 0 && window.scrollY === 0) {
    e.preventDefault()
    pullDistance.value = Math.min(diff * 0.5, MAX_PULL)
  } else {
    pullDistance.value = 0
  }
}

async function onTouchEnd() {
  if (!isPulling.value) return
  isPulling.value = false

  if (pullDistance.value >= PULL_THRESHOLD) {
    isRefreshing.value = true
    pullDistance.value = 60

    await fetchArticles(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })

    isRefreshing.value = false
  }

  pullDistance.value = 0
}

onMounted(() => {
  isTouchDevice.value = 'ontouchstart' in window || navigator.maxTouchPoints > 0

  if (isTouchDevice.value) {
    document.addEventListener('touchstart', onTouchStart, { passive: true })
    document.addEventListener('touchmove', onTouchMove, { passive: false })
    document.addEventListener('touchend', onTouchEnd)
  }

  if (articles.value.length === 0) {
    fetchArticles(true)
  }
})

onUnmounted(() => {
  if (isTouchDevice.value) {
    document.removeEventListener('touchstart', onTouchStart)
    document.removeEventListener('touchmove', onTouchMove)
    document.removeEventListener('touchend', onTouchEnd)
  }
})

function handleRetry() {
  fetchArticles(true)
}
</script>

<template>
  <div ref="feedContainer">
    <!-- Pull-to-refresh indicator -->
    <div
      v-if="isTouchDevice"
      class="pull-indicator"
      :style="{ height: `${pullDistance}px`, opacity: showPullIndicator ? 1 : 0 }"
    >
      <div class="pull-indicator-content">
        <svg
          :class="['pull-icon', { 'spin': isRefreshing }]"
          :style="{ transform: `rotate(${pullProgress * 180}deg)` }"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M4 12a8 8 0 0 1 8-8V1l5 4-5 4V6a6 6 0 0 0-6 6H4z" />
          <path d="M20 12a8 8 0 0 1-8 8v3l-5-4 5-4v3a6 6 0 0 0 6-6h2z" />
        </svg>
        <span class="pull-text">
          {{ isRefreshing ? 'Refreshing...' : pullProgress >= 1 ? 'Release to refresh' : 'Pull to refresh' }}
        </span>
      </div>
    </div>

    <!-- Results count -->
    <p v-if="!loading && articles.length > 0" class="text-xs text-gray-400 dark:text-gray-500 mb-3">
      {{ articles.length }} of {{ total }} articles
    </p>

    <!-- Error state -->
    <ErrorMessage
      v-if="error && !loading"
      :message="error"
      :retryable="true"
      @retry="handleRetry"
      class="mb-6"
    />

    <!-- Loading state (initial) - skeleton cards -->
    <div
      v-if="loading && articles.length === 0"
      class="grid grid-cols-1 lg:grid-cols-2 gap-3"
    >
      <ArticleCardSkeleton v-for="n in 4" :key="n" />
    </div>

    <!-- Articles grid -->
    <TransitionGroup
      v-else-if="articles.length > 0"
      name="articles"
      tag="div"
      class="grid grid-cols-1 lg:grid-cols-2 gap-3"
    >
      <ArticleCard
        v-for="article in articles"
        :key="article.id"
        :article="article"
      />
    </TransitionGroup>

    <!-- Empty state -->
    <div
      v-else-if="!loading && !error"
      class="text-center py-12"
    >
      <p class="text-gray-500 dark:text-gray-400 text-lg">No articles found</p>
      <p class="text-gray-400 dark:text-gray-500 text-sm mt-2">Try adjusting your filters or check back later</p>
    </div>

    <!-- Load more -->
    <div v-if="articles.length > 0" class="mt-6 text-center">
      <button
        v-if="hasMore && !loading"
        @click="loadMore"
        class="px-4 py-2 text-sm bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 font-medium rounded-md hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
      >
        Load more
      </button>

      <LoadingSpinner
        v-else-if="loading"
      />

      <p v-else class="text-gray-300 dark:text-gray-600 text-xs">
        End of articles
      </p>
    </div>
  </div>
</template>

<style scoped>
.articles-enter-active {
  transition: all 0.3s ease-out;
}

.articles-enter-from {
  opacity: 0;
  transform: translateY(20px);
}

.articles-leave-active {
  transition: all 0.2s ease-in;
}

.articles-leave-to {
  opacity: 0;
}

/* Pull-to-refresh styles */
.pull-indicator {
  display: flex;
  align-items: flex-end;
  justify-content: center;
  overflow: hidden;
  transition: opacity 0.2s ease;
}

.pull-indicator-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  padding-bottom: 0.5rem;
  color: #9ca3af;
}

.pull-icon {
  width: 1.25rem;
  height: 1.25rem;
  transition: transform 0.1s ease;
}

.pull-icon.spin {
  animation: spin 1s linear infinite;
}

.pull-text {
  font-size: 0.75rem;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
