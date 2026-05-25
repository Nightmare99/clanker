<script setup lang="ts">
import {
  NConfigProvider,
  NMessageProvider,
  darkTheme,
} from 'naive-ui'
import ConfigPanel from './components/ConfigPanel.vue'

// Neon palette: hotpink / lime / cyan on OLED black
const NEON_PINK = '#ff2bd6'
const NEON_PINK_HOVER = '#ff5ce0'
const NEON_PINK_PRESSED = '#cc1faa'
const NEON_LIME = '#b6ff1a'
const NEON_LIME_HOVER = '#c8ff52'
const NEON_LIME_PRESSED = '#8fcc14'
const NEON_CYAN = '#00f0ff'
const NEON_CYAN_HOVER = '#5cf6ff'
const NEON_CYAN_PRESSED = '#00bcc8'

const themeOverrides = {
  common: {
    bodyColor: '#000000',
    baseColor: '#000000',
    cardColor: '#0a0a0a',
    modalColor: '#0a0a0a',
    popoverColor: '#0a0a0a',
    tableColor: '#0a0a0a',
    inputColor: '#0a0a0a',
    inputColorDisabled: '#050505',
    actionColor: '#0a0a0a',
    tagColor: '#101010',
    dividerColor: 'rgba(255, 43, 214, 0.25)',
    borderColor: 'rgba(0, 240, 255, 0.25)',
    hoverColor: 'rgba(182, 255, 26, 0.08)',
    textColorBase: '#f5f5f5',
    textColor1: '#ffffff',
    textColor2: '#e0e0e0',
    textColor3: '#9aa0a6',
    textColorDisabled: '#555',
    placeholderColor: '#666',
    iconColor: NEON_CYAN,
    iconColorHover: NEON_PINK,
    primaryColor: NEON_PINK,
    primaryColorHover: NEON_PINK_HOVER,
    primaryColorPressed: NEON_PINK_PRESSED,
    primaryColorSuppl: NEON_PINK_HOVER,
    infoColor: NEON_CYAN,
    infoColorHover: NEON_CYAN_HOVER,
    infoColorPressed: NEON_CYAN_PRESSED,
    infoColorSuppl: NEON_CYAN_HOVER,
    successColor: NEON_LIME,
    successColorHover: NEON_LIME_HOVER,
    successColorPressed: NEON_LIME_PRESSED,
    successColorSuppl: NEON_LIME_HOVER,
    warningColor: '#ffe600',
    warningColorHover: '#fff05c',
    warningColorPressed: '#ccb800',
    warningColorSuppl: '#fff05c',
    errorColor: '#ff3b6b',
    errorColorHover: '#ff5c87',
    errorColorPressed: '#cc2f55',
    errorColorSuppl: '#ff5c87',
    fontFamily: '"JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    fontFamilyMono: '"JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    borderRadius: '4px',
    borderRadiusSmall: '3px',
  },
  Card: {
    color: '#0a0a0a',
    colorModal: '#0a0a0a',
    borderColor: 'rgba(0, 240, 255, 0.18)',
    titleTextColor: NEON_CYAN,
  },
  Button: {
    textColorPrimary: '#000000',
    textColorHoverPrimary: '#000000',
    textColorPressedPrimary: '#000000',
    textColorFocusPrimary: '#000000',
    colorPrimary: NEON_PINK,
    colorHoverPrimary: NEON_PINK_HOVER,
    colorPressedPrimary: NEON_PINK_PRESSED,
    colorFocusPrimary: NEON_PINK_HOVER,
    borderPrimary: `1px solid ${NEON_PINK}`,
  },
  Menu: {
    itemColorActive: 'rgba(255, 43, 214, 0.12)',
    itemColorActiveHover: 'rgba(255, 43, 214, 0.20)',
    itemColorActiveCollapsed: 'rgba(255, 43, 214, 0.12)',
    itemTextColorActive: NEON_PINK,
    itemTextColorActiveHover: NEON_PINK,
    itemIconColorActive: NEON_PINK,
    itemIconColorActiveHover: NEON_PINK,
    itemTextColorHover: NEON_CYAN,
    itemIconColorHover: NEON_CYAN,
    arrowColorActive: NEON_PINK,
  },
  Tag: {
    borderRadius: '2px',
  },
  Input: {
    borderHover: `1px solid ${NEON_CYAN}`,
    borderFocus: `1px solid ${NEON_PINK}`,
    boxShadowFocus: `0 0 0 2px rgba(255, 43, 214, 0.25)`,
    caretColor: NEON_PINK,
  },
  InputNumber: {
    iconColor: NEON_CYAN,
  },
  Select: {
    peers: {
      InternalSelection: {
        borderHover: `1px solid ${NEON_CYAN}`,
        borderFocus: `1px solid ${NEON_PINK}`,
        boxShadowFocus: `0 0 0 2px rgba(255, 43, 214, 0.25)`,
      },
    },
  },
  Switch: {
    railColorActive: NEON_LIME,
    boxShadowFocus: `0 0 0 2px rgba(182, 255, 26, 0.35)`,
  },
  Slider: {
    fillColor: NEON_PINK,
    fillColorHover: NEON_PINK_HOVER,
    handleColor: NEON_CYAN,
  },
  Divider: {
    color: 'rgba(255, 43, 214, 0.25)',
  },
  Alert: {
    colorInfo: 'rgba(0, 240, 255, 0.08)',
    borderInfo: `1px solid rgba(0, 240, 255, 0.4)`,
    titleTextColorInfo: NEON_CYAN,
    iconColorInfo: NEON_CYAN,
    colorWarning: 'rgba(255, 230, 0, 0.08)',
    borderWarning: `1px solid rgba(255, 230, 0, 0.4)`,
    titleTextColorWarning: '#ffe600',
    iconColorWarning: '#ffe600',
    colorSuccess: 'rgba(182, 255, 26, 0.08)',
    borderSuccess: `1px solid rgba(182, 255, 26, 0.4)`,
  },
}
</script>

<template>
  <NConfigProvider :theme="darkTheme" :theme-overrides="themeOverrides">
    <NMessageProvider>
      <ConfigPanel />
    </NMessageProvider>
  </NConfigProvider>
</template>

<style>
:root {
  color-scheme: dark;
  --neon-pink: #ff2bd6;
  --neon-lime: #b6ff1a;
  --neon-cyan: #00f0ff;
  --oled-bg: #000000;
  --oled-surface: #0a0a0a;
  --oled-surface-2: #101010;
  --oled-border: rgba(0, 240, 255, 0.2);
}

html, body {
  margin: 0;
  padding: 0;
  background: var(--oled-bg);
  color: #f5f5f5;
  font-family: "JetBrains Mono", "Fira Code", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* Subtle neon backdrop glow */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background:
    radial-gradient(circle at 20% 10%, rgba(255, 43, 214, 0.06), transparent 40%),
    radial-gradient(circle at 80% 90%, rgba(0, 240, 255, 0.06), transparent 40%),
    radial-gradient(circle at 50% 50%, rgba(182, 255, 26, 0.03), transparent 60%);
}

#app {
  position: relative;
  z-index: 1;
}

/* Custom scrollbars */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
::-webkit-scrollbar-track {
  background: #000;
}
::-webkit-scrollbar-thumb {
  background: rgba(255, 43, 214, 0.4);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--neon-pink);
}

/* Selection */
::selection {
  background: var(--neon-pink);
  color: #000;
}
</style>
