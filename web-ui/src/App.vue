<script setup lang="ts">
import { ref, watch, provide, onMounted } from 'vue'
import {
  NConfigProvider,
  NMessageProvider,
  darkTheme,
} from 'naive-ui'
import ConfigPanel from './components/ConfigPanel.vue'

const THEME_KEY = 'clanker-config-theme'

// Color Constants: Lime, Cyan, Hotpink
const HOTPINK = '#ff2bd6'
const HOTPINK_HOVER = '#ff5ce0'
const HOTPINK_PRESSED = '#d914b3'

const CYAN = '#00f0ff'
const CYAN_HOVER = '#5cf6ff'
const CYAN_PRESSED = '#00c5d1'

const LIME = '#b6ff1a'
const LIME_HOVER = '#c8ff52'
const LIME_PRESSED = '#95d909'

const isDark = ref(false)

function applyDocumentTheme(dark: boolean) {
  if (typeof document !== 'undefined') {
    if (dark) {
      document.documentElement.classList.add('dark')
      document.documentElement.setAttribute('data-theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      document.documentElement.setAttribute('data-theme', 'light')
    }
  }
}

onMounted(() => {
  const saved = localStorage.getItem(THEME_KEY)
  if (saved === 'dark' || saved === 'light') {
    isDark.value = saved === 'dark'
  } else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    isDark.value = true
  }
  applyDocumentTheme(isDark.value)
})

function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem(THEME_KEY, isDark.value ? 'dark' : 'light')
  applyDocumentTheme(isDark.value)
}

watch(isDark, (val) => {
  applyDocumentTheme(val)
})

provide('themeState', {
  isDark,
  toggleTheme,
})

// LIGHT THEME: Warm canvas, stark black borders, Lime/Cyan/Hotpink accents
const lightThemeOverrides = {
  common: {
    bodyColor: '#F4F0EA',
    baseColor: '#FFFFFF',
    cardColor: '#FFFFFF',
    modalColor: '#FFFFFF',
    popoverColor: '#FFFFFF',
    tableColor: '#FFFFFF',
    inputColor: '#FFFFFF',
    inputColorDisabled: '#EFEFEF',
    actionColor: '#F4F0EA',
    tagColor: '#FFFFFF',
    dividerColor: '#000000',
    borderColor: '#000000',
    hoverColor: 'rgba(255, 43, 214, 0.15)',
    textColorBase: '#000000',
    textColor1: '#000000',
    textColor2: '#1F2937',
    textColor3: '#4B5563',
    textColorDisabled: '#9CA3AF',
    placeholderColor: '#6B7280',
    iconColor: '#000000',
    iconColorHover: HOTPINK,
    primaryColor: HOTPINK,
    primaryColorHover: HOTPINK_HOVER,
    primaryColorPressed: HOTPINK_PRESSED,
    primaryColorSuppl: HOTPINK,
    infoColor: CYAN,
    infoColorHover: CYAN_HOVER,
    infoColorPressed: CYAN_PRESSED,
    infoColorSuppl: CYAN,
    successColor: '#80CA00',
    successColorHover: '#6EA800',
    successColorPressed: '#568300',
    successColorSuppl: '#80CA00',
    warningColor: '#FF9500',
    warningColorHover: '#EA580C',
    warningColorPressed: '#C2410C',
    warningColorSuppl: '#FF9500',
    errorColor: '#FF1744',
    errorColorHover: '#D50000',
    errorColorPressed: '#B71C1C',
    errorColorSuppl: '#FF1744',
    fontFamily: '"Victor Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    fontFamilyMono: '"Victor Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    borderRadius: '4px',
    borderRadiusSmall: '3px',
  },
  Card: {
    color: '#FFFFFF',
    colorModal: '#FFFFFF',
    borderColor: '#000000',
    titleTextColor: '#000000',
    titleFontWeight: '800',
    borderRadius: '4px',
  },
  Button: {
    textColorPrimary: '#FFFFFF',
    textColorHoverPrimary: '#FFFFFF',
    textColorPressedPrimary: '#FFFFFF',
    textColorFocusPrimary: '#FFFFFF',
    colorPrimary: HOTPINK,
    colorHoverPrimary: HOTPINK_HOVER,
    colorPressedPrimary: HOTPINK_PRESSED,
    colorFocusPrimary: HOTPINK,
    borderPrimary: '2px solid #000000',
    borderHoverPrimary: '2px solid #000000',
    borderPressedPrimary: '2px solid #000000',
    borderFocusPrimary: '2px solid #000000',
    textColor: '#000000',
    textColorHover: '#000000',
    textColorPressed: '#000000',
    textColorFocus: '#000000',
    color: '#FFFFFF',
    colorHover: '#F4F0EA',
    colorPressed: '#E5E0D8',
    colorFocus: '#FFFFFF',
    border: '2px solid #000000',
    borderHover: '2px solid #000000',
    borderPressed: '2px solid #000000',
    borderFocus: '2px solid #000000',
    fontWeight: '700',
    borderRadiusMedium: '4px',
    borderRadiusSmall: '3px',
    borderRadiusTiny: '2px',
    textColorInfo: '#000000',
    colorPrimaryInfo: CYAN,
    colorInfo: CYAN,
    colorHoverInfo: CYAN_HOVER,
    colorPressedInfo: CYAN_PRESSED,
    borderInfo: '2px solid #000000',
    textColorSuccess: '#000000',
    colorSuccess: LIME,
    colorHoverSuccess: LIME_HOVER,
    colorPressedSuccess: LIME_PRESSED,
    borderSuccess: '2px solid #000000',
    textColorError: '#FFFFFF',
    colorError: '#FF1744',
    borderError: '2px solid #000000',
  },
  Menu: {
    itemColorHover: 'transparent',
    itemColorActive: HOTPINK,
    itemColorActiveHover: HOTPINK_HOVER,
    itemColorActiveCollapsed: HOTPINK,
    itemTextColorActive: '#000000',
    itemTextColorActiveHover: '#000000',
    itemIconColorActive: '#000000',
    itemIconColorActiveHover: '#000000',
    itemTextColorHover: '#000000',
    itemIconColorHover: '#000000',
    itemTextColor: '#000000',
    itemIconColor: '#000000',
    arrowColorActive: '#000000',
    borderRadius: '4px',
  },
  Tag: {
    borderRadius: '3px',
    fontWeight: '700',
    textColorDefault: '#000000',
    colorDefault: '#F4F0EA',
  },
  Input: {
    color: '#FFFFFF',
    colorFocus: '#FFFFFF',
    textColor: '#000000',
    border: '2px solid #000000',
    borderHover: '2px solid #000000',
    borderFocus: '2px solid #000000',
    boxShadowFocus: '3px 3px 0px #000000',
    caretColor: HOTPINK,
    borderRadius: '4px',
  },
  InputNumber: {
    iconColor: '#000000',
    iconColorHover: HOTPINK,
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#FFFFFF',
        colorActive: '#FFFFFF',
        textColor: '#000000',
        border: '2px solid #000000',
        borderHover: '2px solid #000000',
        borderFocus: '2px solid #000000',
        borderActive: '2px solid #000000',
        boxShadowFocus: '3px 3px 0px #000000',
        boxShadowActive: '3px 3px 0px #000000',
        borderRadius: '4px',
        arrowColor: '#000000',
      },
    },
  },
  Switch: {
    railColor: '#D1D5DB',
    railColorActive: LIME,
    buttonBoxShadow: '1px 1px 0px #000000',
    boxShadowFocus: '0 0 0 2px #000000',
    buttonColor: '#000000',
  },
  Slider: {
    fillColor: HOTPINK,
    fillColorHover: HOTPINK_HOVER,
    handleColor: CYAN,
    railColor: '#E5E7EB',
    railColorHover: '#D1D5DB',
    dotBorder: '2px solid #000000',
  },
  Divider: {
    color: '#000000',
  },
  Alert: {
    colorInfo: '#E0F7FA',
    borderInfo: '2px solid #000000',
    titleTextColorInfo: '#000000',
    iconColorInfo: '#00838F',
    colorWarning: '#FFFBEA',
    borderWarning: '2px solid #000000',
    titleTextColorWarning: '#000000',
    iconColorWarning: '#D97706',
    colorSuccess: '#E8F8EE',
    borderSuccess: '2px solid #000000',
    titleTextColorSuccess: '#000000',
    iconColorSuccess: '#16A34A',
    colorError: '#FFE8EC',
    borderError: '2px solid #000000',
    titleTextColorError: '#000000',
    iconColorError: '#E11D48',
  },
  Modal: {
    color: '#FFFFFF',
    textColor: '#000000',
    titleTextColor: '#000000',
    borderRadius: '4px',
  },
  Dialog: {
    color: '#FFFFFF',
    textColor: '#000000',
    titleTextColor: '#000000',
    borderRadius: '4px',
  },
  Tooltip: {
    color: '#FFFFFF',
    textColor: '#000000',
    borderRadius: '4px',
  },
  Popover: {
    color: '#FFFFFF',
    textColor: '#000000',
    borderRadius: '4px',
  },
}

// DARK THEME: AMOLED slate, crisp high-contrast borders, lime/cyan/hotpink neo-brutalist accents
const darkThemeOverrides = {
  common: {
    bodyColor: '#0D0E12',
    baseColor: '#16181D',
    cardColor: '#16181D',
    modalColor: '#16181D',
    popoverColor: '#1D2026',
    tableColor: '#16181D',
    inputColor: '#121318',
    inputColorDisabled: '#0A0B0E',
    actionColor: '#1D2026',
    tagColor: '#1D2026',
    dividerColor: 'rgba(255, 255, 255, 0.18)',
    borderColor: 'rgba(255, 255, 255, 0.45)',
    hoverColor: 'rgba(255, 43, 214, 0.15)',
    textColorBase: '#F4F4F6',
    textColor1: '#F4F4F6',
    textColor2: '#D4D4D8',
    textColor3: '#949AA5',
    textColorDisabled: '#52525B',
    placeholderColor: '#71717A',
    iconColor: '#949AA5',
    iconColorHover: HOTPINK,
    primaryColor: HOTPINK,
    primaryColorHover: HOTPINK_HOVER,
    primaryColorPressed: HOTPINK_PRESSED,
    primaryColorSuppl: HOTPINK,
    infoColor: CYAN,
    infoColorHover: CYAN_HOVER,
    infoColorPressed: CYAN_PRESSED,
    infoColorSuppl: CYAN,
    successColor: LIME,
    successColorHover: LIME_HOVER,
    successColorPressed: LIME_PRESSED,
    successColorSuppl: LIME,
    warningColor: '#FFE600',
    warningColorHover: '#FFF05C',
    warningColorPressed: '#CCB800',
    warningColorSuppl: '#FFE600',
    errorColor: '#FF3366',
    errorColorHover: '#FF5C87',
    errorColorPressed: '#CC2852',
    errorColorSuppl: '#FF3366',
    fontFamily: '"Victor Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    fontFamilyMono: '"Victor Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    borderRadius: '4px',
    borderRadiusSmall: '3px',
  },
  Card: {
    color: '#16181D',
    colorModal: '#16181D',
    borderColor: '#FFFFFF',
    titleTextColor: '#F4F4F6',
    titleFontWeight: '800',
    borderRadius: '4px',
  },
  Button: {
    textColorPrimary: '#000000',
    textColorHoverPrimary: '#000000',
    textColorPressedPrimary: '#000000',
    textColorFocusPrimary: '#000000',
    colorPrimary: HOTPINK,
    colorHoverPrimary: HOTPINK_HOVER,
    colorPressedPrimary: HOTPINK_PRESSED,
    colorFocusPrimary: HOTPINK,
    borderPrimary: '2px solid #FFFFFF',
    borderHoverPrimary: '2px solid #FFFFFF',
    borderPressedPrimary: '2px solid #FFFFFF',
    borderFocusPrimary: '2px solid #FFFFFF',
    textColor: '#F4F4F6',
    textColorHover: HOTPINK,
    textColorPressed: '#FFFFFF',
    textColorFocus: '#F4F4F6',
    color: '#1D2026',
    colorHover: '#252932',
    colorPressed: '#16181D',
    colorFocus: '#1D2026',
    border: '1.5px solid rgba(255, 255, 255, 0.45)',
    borderHover: `1.5px solid ${HOTPINK}`,
    borderPressed: '1.5px solid rgba(255, 255, 255, 0.45)',
    borderFocus: `1.5px solid ${HOTPINK}`,
    fontWeight: '700',
    borderRadiusMedium: '4px',
    borderRadiusSmall: '3px',
    borderRadiusTiny: '2px',
    textColorInfo: '#000000',
    colorPrimaryInfo: CYAN,
    colorInfo: CYAN,
    colorHoverInfo: CYAN_HOVER,
    colorPressedInfo: CYAN_PRESSED,
    borderInfo: '2px solid #FFFFFF',
    textColorSuccess: '#000000',
    colorSuccess: LIME,
    colorHoverSuccess: LIME_HOVER,
    colorPressedSuccess: LIME_PRESSED,
    borderSuccess: '2px solid #FFFFFF',
    textColorError: '#FFFFFF',
    colorError: '#FF3366',
    borderError: '2px solid #FFFFFF',
  },
  Menu: {
    itemColorHover: 'transparent',
    itemColorActive: HOTPINK,
    itemColorActiveHover: HOTPINK_HOVER,
    itemColorActiveCollapsed: HOTPINK,
    itemTextColorActive: '#000000',
    itemTextColorActiveHover: '#000000',
    itemIconColorActive: '#000000',
    itemIconColorActiveHover: '#000000',
    itemTextColorHover: '#F4F4F6',
    itemIconColorHover: '#F4F4F6',
    itemTextColor: '#E4E4E7',
    itemIconColor: '#E4E4E7',
    arrowColorActive: '#000000',
    borderRadius: '4px',
  },
  Tag: {
    borderRadius: '3px',
    fontWeight: '700',
    textColorDefault: '#F4F4F6',
    colorDefault: '#1D2026',
  },
  Input: {
    color: '#121318',
    colorFocus: '#121318',
    textColor: '#F4F4F6',
    border: '1.5px solid rgba(255, 255, 255, 0.45)',
    borderHover: `1.5px solid ${HOTPINK}`,
    borderFocus: `2px solid ${HOTPINK}`,
    boxShadowFocus: `3px 3px 0px ${HOTPINK}`,
    caretColor: HOTPINK,
    borderRadius: '4px',
  },
  InputNumber: {
    iconColor: CYAN,
    iconColorHover: HOTPINK,
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#121318',
        colorActive: '#121318',
        textColor: '#F4F4F6',
        border: '1.5px solid rgba(255, 255, 255, 0.45)',
        borderHover: `1.5px solid ${HOTPINK}`,
        borderFocus: `2px solid ${HOTPINK}`,
        borderActive: `2px solid ${HOTPINK}`,
        boxShadowFocus: `3px 3px 0px ${HOTPINK}`,
        boxShadowActive: `3px 3px 0px ${HOTPINK}`,
        borderRadius: '4px',
        arrowColor: '#949AA5',
      },
    },
  },
  Switch: {
    railColor: '#27272A',
    railColorActive: LIME,
    buttonBoxShadow: '1px 1px 0px #000000',
    boxShadowFocus: `0 0 0 2px ${LIME}`,
    buttonColor: '#000000',
  },
  Slider: {
    fillColor: HOTPINK,
    fillColorHover: HOTPINK_HOVER,
    handleColor: CYAN,
    railColor: '#27272A',
    railColorHover: '#3F3F46',
    dotBorder: `2px solid ${CYAN}`,
  },
  Divider: {
    color: 'rgba(255, 255, 255, 0.18)',
  },
  Alert: {
    colorInfo: '#041B22',
    borderInfo: `2px solid ${CYAN}`,
    titleTextColorInfo: CYAN,
    iconColorInfo: CYAN,
    colorWarning: '#241E02',
    borderWarning: '2px solid #FFE600',
    titleTextColorWarning: '#FFE600',
    iconColorWarning: '#FFE600',
    colorSuccess: '#0E1F03',
    borderSuccess: `2px solid ${LIME}`,
    titleTextColorSuccess: LIME,
    iconColorSuccess: LIME,
    colorError: '#250514',
    borderError: `2px solid ${HOTPINK}`,
    titleTextColorError: HOTPINK,
    iconColorError: HOTPINK,
  },
  Modal: {
    color: '#16181D',
    textColor: '#F4F4F6',
    titleTextColor: '#F4F4F6',
    borderRadius: '4px',
  },
  Dialog: {
    color: '#16181D',
    textColor: '#F4F4F6',
    titleTextColor: '#F4F4F6',
    borderRadius: '4px',
  },
  Tooltip: {
    color: '#16181D',
    textColor: '#F4F4F6',
    borderRadius: '4px',
  },
  Popover: {
    color: '#16181D',
    textColor: '#F4F4F6',
    borderRadius: '4px',
  },
}
</script>

<template>
  <NConfigProvider
    :theme="isDark ? darkTheme : null"
    :theme-overrides="isDark ? darkThemeOverrides : lightThemeOverrides"
  >
    <NMessageProvider>
      <ConfigPanel />
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Victor+Mono:wght@400;500;600;700;800&display=swap');

/* CSS Tokens - Light Theme */
:root {
  color-scheme: light;
  --nb-canvas: #F4F0EA;
  --nb-surface: #FFFFFF;
  --nb-surface-secondary: #F0EAE1;
  --nb-surface-inset: #F8F6F2;
  --nb-menu-hover-bg: #FFFFFF;
  --nb-ink: #000000;
  --nb-ink-muted: #4B5563;
  --nb-border: #000000;
  --nb-border-subtle: rgba(0, 0, 0, 0.18);
  --nb-pink: #FF2BD6;
  --nb-cyan: #00F0FF;
  --nb-lime: #B6FF1A;
  --nb-shadow: 4px 4px 0px #000000;
  --nb-shadow-sm: 2px 2px 0px #000000;
  --nb-shadow-btn: 3px 3px 0px #000000;
  --nb-shadow-lg: 6px 6px 0px #000000;
  --nb-card-default-shadow: 5px 5px 0px var(--nb-lime);
  --nb-card-hover-shadow: 5px 5px 0px #000000;
  --nb-card-hover-border: #000000;
  --nb-dot-color: #000000;
  --nb-dot-opacity: 0.05;
  --nb-scrollbar-track: #F4F0EA;
  --nb-scrollbar-thumb: #000000;
  --nb-scrollbar-hover: #FF2BD6;
  --nb-selection-bg: #FF2BD6;
  --nb-selection-color: #FFFFFF;
  --nb-hint-bg: #FFFDF0;
  --nb-hint-border: #FF2BD6;
}

/* CSS Tokens - Dark Theme (Refined High-Contrast Neo-Brutalism) */
:root.dark,
html.dark {
  color-scheme: dark;
  --nb-canvas: #0D0E12;
  --nb-surface: #16181D;
  --nb-surface-secondary: #1D2026;
  --nb-surface-inset: #121318;
  --nb-menu-hover-bg: #222630;
  --nb-ink: #F4F4F6;
  --nb-ink-muted: #949AA5;
  --nb-border: #FFFFFF;
  --nb-border-subtle: rgba(255, 255, 255, 0.18);
  --nb-pink: #FF2BD6;
  --nb-cyan: #00F0FF;
  --nb-lime: #B6FF1A;
  --nb-shadow: 4px 4px 0px #000000;
  --nb-shadow-sm: 2px 2px 0px #000000;
  --nb-shadow-btn: 3px 3px 0px var(--nb-lime);
  --nb-shadow-lg: 6px 6px 0px #000000;
  --nb-card-default-shadow: 5px 5px 0px var(--nb-lime);
  --nb-card-hover-shadow: 5px 5px 0px var(--nb-pink);
  --nb-card-hover-border: var(--nb-pink);
  --nb-dot-color: #FFFFFF;
  --nb-dot-opacity: 0.04;
  --nb-scrollbar-track: #0D0E12;
  --nb-scrollbar-thumb: #2D333F;
  --nb-scrollbar-hover: var(--nb-pink);
  --nb-selection-bg: #FF2BD6;
  --nb-selection-color: #000000;
  --nb-hint-bg: #1A1218;
  --nb-hint-border: #FF2BD6;
}

*, *::before, *::after {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  background: var(--nb-canvas);
  color: var(--nb-ink);
  font-family: "Victor Mono", "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  -webkit-font-smoothing: antialiased;
  transition: background-color 0.15s ease, color 0.15s ease;
}

/* Subtle neo-brutalist dot pattern */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image: radial-gradient(var(--nb-dot-color) 0.75px, transparent 0.75px);
  background-size: 20px 20px;
  opacity: var(--nb-dot-opacity);
}

#app {
  position: relative;
  z-index: 1;
}

/* Neo-Brutalist Global Component Enhancements */
.n-button {
  font-weight: 700 !important;
  border-radius: 4px !important;
  transition: transform 0.08s ease, box-shadow 0.08s ease, background-color 0.08s ease, border-color 0.08s ease !important;
}

/* Primary CTA Buttons */
.n-button--primary-type {
  border: 2px solid var(--nb-border) !important;
  box-shadow: var(--nb-shadow-btn) !important;
  font-weight: 800 !important;
}

.n-button--primary-type:hover:not(:disabled) {
  transform: translate(-1px, -1px) !important;
  box-shadow: 4px 4px 0px var(--nb-border) !important;
}

.n-button--primary-type:active:not(:disabled) {
  transform: translate(2px, 2px) !important;
  box-shadow: 1px 1px 0px var(--nb-border) !important;
}

/* Default / Secondary Buttons */
.n-button--default-type {
  border: 1.5px solid var(--nb-border) !important;
  box-shadow: none !important;
  background: var(--nb-surface) !important;
  color: var(--nb-ink) !important;
}

.n-button--default-type:hover:not(:disabled) {
  transform: translate(-1px, -1px) !important;
  border-color: var(--nb-pink) !important;
  color: var(--nb-pink) !important;
  box-shadow: 2px 2px 0px var(--nb-pink) !important;
}

.n-button--default-type:active:not(:disabled) {
  transform: translate(1px, 1px) !important;
  box-shadow: none !important;
}

/* Quaternary / Ghost Buttons */
.n-button--quaternary {
  box-shadow: none !important;
  border: 1.5px dashed var(--nb-border-subtle) !important;
}

.n-button--quaternary:hover:not(:disabled) {
  background: var(--nb-pink) !important;
  color: #FFFFFF !important;
  border-style: solid !important;
  border-color: var(--nb-border) !important;
  transform: translate(-1px, -1px) !important;
  box-shadow: 2px 2px 0px var(--nb-border) !important;
}

.n-card {
  border: 2px solid var(--nb-border) !important;
  box-shadow: var(--nb-shadow) !important;
  background: var(--nb-surface) !important;
  border-radius: 4px !important;
}

/* Inputs and Selects: flat at rest with crisp borders, pop on focus */
.n-input,
.n-input-number,
.n-base-selection {
  border: 2px solid var(--nb-border) !important;
  border-radius: 4px !important;
  background: var(--nb-surface) !important;
  box-shadow: none !important;
  transition: box-shadow 0.12s ease, border-color 0.12s ease !important;
}

.n-input:focus-within,
.n-input-number:focus-within,
.n-base-selection--active,
.n-base-selection:focus-within {
  border-color: var(--nb-pink) !important;
  box-shadow: 3px 3px 0px var(--nb-pink) !important;
}

/* Badges / Tags: flat with crisp border, no distracting drop shadow */
.n-tag {
  border: 1.5px solid var(--nb-border) !important;
  box-shadow: none !important;
  font-weight: 700 !important;
  border-radius: 3px !important;
}

.n-alert {
  border: 2px solid var(--nb-border) !important;
  box-shadow: var(--nb-shadow-btn) !important;
  border-radius: 4px !important;
}

.n-modal.n-card {
  border: 3px solid var(--nb-border) !important;
  box-shadow: var(--nb-shadow-lg) !important;
}

.n-popover,
.n-tooltip,
.n-dropdown-menu,
.n-select-menu {
  border: 2px solid var(--nb-border) !important;
  box-shadow: var(--nb-shadow) !important;
  background: var(--nb-surface) !important;
  color: var(--nb-ink) !important;
}

.n-popover .n-popover__content,
.n-tooltip .n-popover__content,
.n-tooltip {
  color: var(--nb-ink) !important;
  font-weight: 700 !important;
}

.n-popover-arrow {
  display: none !important;
}

.n-switch {
  border: 2px solid var(--nb-border) !important;
  border-radius: 12px !important;
}

/* Custom Scrollbars */
::-webkit-scrollbar {
  width: 9px;
  height: 9px;
}

::-webkit-scrollbar-track {
  background: var(--nb-scrollbar-track);
  border-left: 1.5px solid var(--nb-border);
}

::-webkit-scrollbar-thumb {
  background: var(--nb-scrollbar-thumb);
  border: 2px solid var(--nb-scrollbar-track);
  border-radius: 0;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--nb-scrollbar-hover);
}

/* Selection */
::selection {
  background: var(--nb-selection-bg);
  color: var(--nb-selection-color);
}
</style>
