import { ref } from 'vue'

// Initialize immediately to match the state set by index.html script
function getInitialDarkMode() {
  if (typeof window === 'undefined') return false
  const stored = localStorage.getItem('darkMode')
  if (stored !== null) {
    return stored === 'true'
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

const isDark = ref(getInitialDarkMode())

function apply() {
  if (isDark.value) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
  localStorage.setItem('darkMode', isDark.value ? 'true' : 'false')
}

function toggle() {
  isDark.value = !isDark.value
  apply()
}

export function useDarkMode() {
  return {
    isDark,
    toggle,
  }
}
