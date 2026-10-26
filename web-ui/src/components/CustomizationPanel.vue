<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  NButton,
  NCard,
  NSpace,
  NInput,
  NSwitch,
  NColorPicker,
  NPopconfirm,
  NTag,
  NSpin,
  useMessage,
} from 'naive-ui'

interface ColorPalette {
  background: string
  surface: string
  foreground: string
  primary: string
  secondary: string
  status_bar_bg: string
  status_bar_model: string
  status_bar_tokens: string
  status_bar_subagents: string
  bottom_bar_bg: string
  bottom_bar_text: string
  bottom_bar_session: string
  bottom_bar_context: string
  prompt_bar_bg: string
  prompt_symbol: string
  input_bg: string
  input_text: string
  queue_bg: string
  queue_text: string
  todo_bg: string
  todo_text: string
  chat_log_bg: string
  user_msg: string
  assistant_msg: string
  system_msg: string
  tool_card: string
  thinking_card: string
  divider: string
  turn_separator: string
  notify_info: string
  notify_success: string
  notify_warning: string
  notify_error: string
}

interface HeroTheme {
  ascii_art: string
  animation_enabled: boolean
  gradient_start: string
  gradient_end: string
  system_online_color: string
  model_label_color: string
  model_name_color: string
}

interface UIThemeConfig {
  preset: string
  palette: ColorPalette
  hero: HeroTheme
}

interface PresetItem {
  name: string
  description: string
  palette: ColorPalette
  hero: HeroTheme
}

const message = useMessage()
const loading = ref(true)
const saving = ref(false)
const hasChanges = ref(false)
const themePath = ref('')
const defaultAsciiArt = ref('')
const sampleAsciiArts = ref<Record<string, string>>({})
const presets = ref<Record<string, PresetItem>>({})

const currentTheme = ref<UIThemeConfig>({
  preset: 'default',
  palette: {
    background: '#000000',
    surface: '#0f0f0f',
    foreground: '#c8c8c8',
    primary: '#b4ff3c',
    secondary: '#00f0f0',
    status_bar_bg: '#0f0f0f',
    status_bar_model: '#00f0f0',
    status_bar_tokens: '#646464',
    status_bar_subagents: '#00f0f0',
    bottom_bar_bg: '#000000',
    bottom_bar_text: '#8c8c8c',
    bottom_bar_session: '#b4ff3c',
    bottom_bar_context: '#ffdc3c',
    prompt_bar_bg: '#000000',
    prompt_symbol: '#00f0f0',
    input_bg: '#000000',
    input_text: '#c8c8c8',
    queue_bg: '#000000',
    queue_text: '#969696',
    todo_bg: '#000000',
    todo_text: '#b4b4b4',
    chat_log_bg: '#000000',
    user_msg: '#00f0f0',
    assistant_msg: '#c8c8c8',
    system_msg: '#00f0f0',
    tool_card: '#c8c8c8',
    thinking_card: '#b48cff',
    divider: '#00f0f0',
    turn_separator: '#3c3c50',
    notify_info: '#00f0f0',
    notify_success: '#b4ff3c',
    notify_warning: '#ffdc3c',
    notify_error: '#ff69b4',
  },
  hero: {
    ascii_art: '',
    animation_enabled: true,
    gradient_start: '#00f0f0',
    gradient_end: '#64beff',
    system_online_color: '#00f0f0',
    model_label_color: '#ffffff',
    model_name_color: '#64beff',
  },
})

// Color interpolation for preview
function hexToRgb(hex: string): [number, number, number] {
  let c = hex.replace('#', '').trim()
  if (c.length === 3) c = c.split('').map(x => x + x).join('')
  const num = parseInt(c, 16)
  if (isNaN(num)) return [0, 240, 240]
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255]
}

function interpolateHex(c1: string, c2: string, factor: number): string {
  const [r1, g1, b1] = hexToRgb(c1)
  const [r2, g2, b2] = hexToRgb(c2)
  const f = Math.max(0, Math.min(1, factor))
  const r = Math.round(r1 + (r2 - r1) * f)
  const g = Math.round(g1 + (g2 - g1) * f)
  const b = Math.round(b1 + (b2 - b1) * f)
  return `rgb(${r}, ${g}, ${b})`
}

// Animation phase for ASCII live preview
const animPhase = ref(0)
let animTimer: number | null = null

onMounted(async () => {
  await fetchTheme()
  animTimer = window.setInterval(() => {
    if (currentTheme.value.hero.animation_enabled) {
      animPhase.value = (animPhase.value + 0.05) % 1.0
    }
  }, 80)
})

onUnmounted(() => {
  if (animTimer !== null) {
    clearInterval(animTimer)
  }
})

async function fetchTheme() {
  loading.value = true
  try {
    const res = await fetch('/api/theme')
    if (res.ok) {
      const data = await res.json()
      currentTheme.value = data.theme
      presets.value = data.presets
      defaultAsciiArt.value = data.default_ascii_art
      sampleAsciiArts.value = data.sample_ascii_arts || {}
      themePath.value = data.theme_path
      hasChanges.value = false
    } else {
      message.error('Failed to load theme configuration')
    }
  } catch (e) {
    message.error('Network error loading theme')
  } finally {
    loading.value = false
  }
}

async function saveTheme() {
  saving.value = true
  try {
    const res = await fetch('/api/theme', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentTheme.value),
    })
    if (res.ok) {
      message.success('Theme saved successfully! Restart or /reload clanker to view changes.')
      hasChanges.value = false
    } else {
      const err = await res.json()
      message.error(`Failed to save theme: ${err.detail || 'Unknown error'}`)
    }
  } catch (e) {
    message.error('Network error saving theme')
  } finally {
    saving.value = false
  }
}

async function resetTheme() {
  saving.value = true
  try {
    const res = await fetch('/api/theme/reset', { method: 'POST' })
    if (res.ok) {
      const data = await res.json()
      currentTheme.value = data.theme
      presets.value = data.presets
      hasChanges.value = false
      message.success('Theme reset to defaults')
    } else {
      message.error('Failed to reset theme')
    }
  } catch (e) {
    message.error('Network error resetting theme')
  } finally {
    saving.value = false
  }
}

function applyPreset(presetKey: string) {
  const p = presets.value[presetKey]
  if (!p) return
  currentTheme.value.preset = presetKey
  currentTheme.value.palette = JSON.parse(JSON.stringify(p.palette))
  currentTheme.value.hero = {
    ...currentTheme.value.hero,
    ...JSON.parse(JSON.stringify(p.hero)),
  }
  hasChanges.value = true
  message.info(`Applied "${p.name}" preset`)
}

function markChanged() {
  hasChanges.value = true
  currentTheme.value.preset = 'custom'
}

function setSampleArt(artKey: string) {
  const art = sampleAsciiArts.value[artKey]
  if (art) {
    currentTheme.value.hero.ascii_art = art
    markChanged()
  }
}

// Compute lines of ASCII art for preview
const previewAsciiLines = computed(() => {
  const art = (currentTheme.value.hero.ascii_art || '').trim() || defaultAsciiArt.value
  return art.split('\n')
})

function getCharColor(col: number, row: number): string {
  const phase = currentTheme.value.hero.animation_enabled ? animPhase.value : 0
  const wave = (col * 0.04 + row * 0.12 + phase) % 1.0
  const factor = (1 + Math.cos(wave * 2 * Math.PI)) / 2
  return interpolateHex(
    currentTheme.value.hero.gradient_start,
    currentTheme.value.hero.gradient_end,
    factor
  )
}
</script>

<template>
  <div class="customization-panel">
    <NSpin :show="loading">
      <div class="customization-stack">
        <div class="section-intro">
        <div class="intro-main">
          <h2>TUI Appearance & Customization</h2>
          <p class="intro-desc">
            Configure the color palette across every terminal element, customize the hero ASCII art,
            adjust the gradient banner shimmer animation, or pick a curated theme preset.
          </p>
        </div>
        <div class="intro-actions">
          <NTag v-if="themePath" size="small" :bordered="false" class="path-tag">
            {{ themePath }}
          </NTag>
          <NSpace :size="8">
            <NPopconfirm @positive-click="resetTheme">
              <template #trigger>
                <NButton size="small" tertiary :disabled="saving">
                  Reset Defaults
                </NButton>
              </template>
              Are you sure you want to reset all theme customizations to default?
            </NPopconfirm>
            <NButton
              type="primary"
              size="small"
              :loading="saving"
              :disabled="!hasChanges"
              @click="saveTheme"
            >
              {{ hasChanges ? 'Save Theme Changes' : 'Saved' }}
            </NButton>
          </NSpace>
        </div>
      </div>

      <!-- Presets Selector -->
      <NCard class="panel-card presets-card" title="Theme Presets" size="small">
        <p class="card-hint">
          Click any preset to instantly apply its colors and styling. You can fine-tune individual colors below.
        </p>
        <div class="presets-grid">
          <div
            v-for="(presetData, pKey) in presets"
            :key="pKey"
            class="preset-item"
            :class="{ active: currentTheme.preset === pKey }"
            @click="applyPreset(String(pKey))"
          >
            <div class="preset-header">
              <span class="preset-name">{{ presetData.name }}</span>
              <span v-if="currentTheme.preset === pKey" class="active-badge">ACTIVE</span>
            </div>
            <p class="preset-desc">{{ presetData.description }}</p>
            <div class="preset-swatches">
              <span
                class="swatch"
                :style="{ background: presetData.palette.background }"
                title="Background"
              />
              <span
                class="swatch"
                :style="{ background: presetData.hero.gradient_start }"
                title="Gradient Start"
              />
              <span
                class="swatch"
                :style="{ background: presetData.hero.gradient_end }"
                title="Gradient End"
              />
              <span
                class="swatch"
                :style="{ background: presetData.palette.user_msg }"
                title="User Message"
              />
              <span
                class="swatch"
                :style="{ background: presetData.palette.primary }"
                title="Primary Accent"
              />
              <span
                class="swatch"
                :style="{ background: presetData.palette.notify_error }"
                title="Accent 2"
              />
            </div>
          </div>
        </div>
      </NCard>

      <!-- Live Interactive Preview -->
      <NCard class="panel-card preview-card" title="Interactive TUI Live Preview" size="small">
        <div class="preview-layout" :style="{ background: currentTheme.palette.background }">
          <!-- Terminal Header Bar -->
          <div class="preview-term-header">
            <span class="dot dot-red" />
            <span class="dot dot-yellow" />
            <span class="dot dot-green" />
            <span class="term-title">clanker — Terminal Preview</span>
          </div>

          <!-- Top Status Bar -->
          <div
            class="preview-status-bar"
            :style="{
              background: currentTheme.palette.status_bar_bg,
              color: currentTheme.palette.status_bar_tokens,
              borderBottom: '1px solid ' + currentTheme.palette.turn_separator,
            }"
          >
            <span class="preview-subagents" :style="{ color: currentTheme.palette.status_bar_subagents }">
              ⚡ 0 subagents
            </span>
            <span class="preview-tokens" :style="{ color: currentTheme.palette.status_bar_tokens }">
              tokens: 1,420 in / 380 out
            </span>
            <span class="preview-model" :style="{ color: currentTheme.palette.status_bar_model, fontWeight: 'bold' }">
              claude-3-7-sonnet
            </span>
          </div>

          <!-- Chat Log Viewport -->
          <div class="preview-chat-viewport" :style="{ background: currentTheme.palette.chat_log_bg }">
            <!-- Hero Banner -->
            <div class="preview-hero">
              <pre class="ascii-art-block"><template v-for="(line, r) in previewAsciiLines" :key="r"><span v-for="(ch, c) in line" :key="c" :style="{ color: getCharColor(c, r) }">{{ ch }}</span><br /></template></pre>
              <div
                class="hero-status-line"
                :style="{ color: currentTheme.hero.system_online_color, fontWeight: 'bold' }"
              >
                Systems online. Circuits humming. Ready to build.
              </div>
              <div class="hero-model-line">
                <span :style="{ color: currentTheme.hero.model_label_color }">Model: </span>
                <span :style="{ color: currentTheme.hero.model_name_color, fontWeight: 'bold' }">
                  claude-3-7-sonnet
                </span>
              </div>
            </div>

            <!-- Divider -->
            <div class="preview-rule" :style="{ borderTopColor: currentTheme.palette.divider }" />

            <!-- Messages Stream -->
            <div class="preview-msg msg-user">
              <span class="msg-author" :style="{ color: currentTheme.palette.user_msg }">❯ User</span>
              <p :style="{ color: currentTheme.palette.user_msg }">
                Refactor tests and verify the new theme customizer!
              </p>
            </div>

            <div
              class="preview-card-block"
              :style="{
                borderLeftColor: currentTheme.palette.tool_card,
                background: 'rgba(255,255,255,0.02)',
              }"
            >
              <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                <span :style="{ background: currentTheme.palette.tool_card, color: '#000', fontWeight: 'bold', padding: '1px 6px', borderRadius: '3px', fontSize: '0.72rem' }">
                  execute_shell
                </span>
                <span :style="{ color: currentTheme.palette.foreground, opacity: 0.8, fontSize: '0.75rem' }">
                  pytest tests/test_theme.py
                </span>
              </div>
              <div class="code-line" :style="{ color: currentTheme.palette.notify_success, fontWeight: 'bold' }">
                ✓ 24 passed in 0.42s
              </div>
            </div>

            <div
              class="preview-card-block thinking"
              :style="{ borderLeftColor: currentTheme.palette.thinking_card }"
            >
              <span :style="{ color: currentTheme.palette.thinking_card }">
                🧠 Thinking: All test assertions passed cleanly.
              </span>
            </div>

            <div class="preview-msg msg-assistant">
              <span class="msg-author" :style="{ color: currentTheme.palette.primary }">● Clanker</span>
              <p :style="{ color: currentTheme.palette.assistant_msg }">
                The theme configuration has been saved. All components reflect your custom palette in real-time.
              </p>
            </div>

            <!-- Turn Separator -->
            <div
              class="preview-separator"
              :style="{ borderTopColor: currentTheme.palette.turn_separator }"
            />
          </div>

          <!-- Bottom Prompt Input Area -->
          <div
            class="preview-input-area"
            :style="{
              background: currentTheme.palette.prompt_bar_bg,
              borderTop: '1px solid ' + currentTheme.palette.turn_separator,
            }"
          >
            <div
              class="preview-prompt-bar"
              :style="{ background: 'transparent' }"
            >
              <span
                class="prompt-symbol"
                :style="{ color: currentTheme.palette.prompt_symbol, fontWeight: 'bold' }"
              >&gt;</span>
              <div
                class="preview-input-box"
                :style="{
                  background: 'transparent',
                  color: currentTheme.palette.input_text,
                }"
              >
                Type your message... (Ctrl+C interrupt)
              </div>
            </div>

            <!-- Workspace Status Line -->
            <div
              class="preview-workspace-status"
              :style="{
                background: currentTheme.palette.bottom_bar_bg,
                color: currentTheme.palette.bottom_bar_text,
              }"
            >
              <span
                class="status-session"
                :style="{ color: currentTheme.palette.bottom_bar_session, fontWeight: 'bold' }"
              >
                Session ID: 4a9f2e
              </span>
              <span class="status-hint">F1 Help · F3 History · /reload to refresh</span>
            </div>
          </div>
        </div>
      </NCard>

      <!-- Hero Banner & ASCII Art Settings -->
      <NCard class="panel-card" title="Hero Banner & ASCII Art" size="small">
        <div class="hero-card-grid">
          <div class="setting-group hero-art-group">
            <div class="setting-label-row">
              <span class="setting-title">Hero ASCII Art</span>
              <NSpace :size="6">
                <NButton
                  v-for="(_, artKey) in sampleAsciiArts"
                  :key="artKey"
                  size="tiny"
                  quaternary
                  @click="setSampleArt(String(artKey))"
                >
                  {{ artKey }}
                </NButton>
              </NSpace>
            </div>
            <p class="setting-help">
              Set custom banner ASCII text. Leave blank to use standard CLNKR banner.
            </p>
            <NInput
              v-model:value="currentTheme.hero.ascii_art"
              type="textarea"
              placeholder="Paste ASCII art here..."
              class="mono-textarea"
              @update:value="markChanged"
            />
          </div>

          <div class="setting-group">
            <span class="setting-title">Banner Animation & Gradient Controls</span>
            <p class="setting-help">
              Toggle the shimmering color-wash and typewriter slide-in animation, and choose gradient transition hues.
            </p>

            <div class="field-row">
              <div class="field-info">
                <span class="field-name">Enable Animation</span>
                <span class="field-sub">Continuous shimmer gradient and typewriter sweep</span>
              </div>
              <NSwitch
                v-model:value="currentTheme.hero.animation_enabled"
                @update:value="markChanged"
              />
            </div>

            <div class="color-picker-row">
              <div class="color-label">
                <span class="field-name">Gradient Start Color</span>
                <span class="field-sub">Starting tint of banner wash</span>
              </div>
              <div class="picker-controls">
                <NColorPicker
                  v-model:value="currentTheme.hero.gradient_start"
                  :show-alpha="false"
                  class="color-picker"
                  @update:value="markChanged"
                />
                <NInput
                  v-model:value="currentTheme.hero.gradient_start"
                  size="small"
                  class="hex-input"
                  @update:value="markChanged"
                />
              </div>
            </div>

            <div class="color-picker-row">
              <div class="color-label">
                <span class="field-name">Gradient End Color</span>
                <span class="field-sub">Ending tint of banner wash</span>
              </div>
              <div class="picker-controls">
                <NColorPicker
                  v-model:value="currentTheme.hero.gradient_end"
                  :show-alpha="false"
                  class="color-picker"
                  @update:value="markChanged"
                />
                <NInput
                  v-model:value="currentTheme.hero.gradient_end"
                  size="small"
                  class="hex-input"
                  @update:value="markChanged"
                />
              </div>
            </div>

            <div class="color-picker-row">
              <div class="color-label">
                <span class="field-name">Systems Online Text</span>
                <span class="field-sub">Color of boot ready message</span>
              </div>
              <div class="picker-controls">
                <NColorPicker
                  v-model:value="currentTheme.hero.system_online_color"
                  :show-alpha="false"
                  class="color-picker"
                  @update:value="markChanged"
                />
                <NInput
                  v-model:value="currentTheme.hero.system_online_color"
                  size="small"
                  class="hex-input"
                  @update:value="markChanged"
                />
              </div>
            </div>

            <div class="color-picker-row">
              <div class="color-label">
                <span class="field-name">Model Name Color</span>
                <span class="field-sub">Color of active model label</span>
              </div>
              <div class="picker-controls">
                <NColorPicker
                  v-model:value="currentTheme.hero.model_name_color"
                  :show-alpha="false"
                  class="color-picker"
                  @update:value="markChanged"
                />
                <NInput
                  v-model:value="currentTheme.hero.model_name_color"
                  size="small"
                  class="hex-input"
                  @update:value="markChanged"
                />
              </div>
            </div>
          </div>
        </div>
      </NCard>

      <!-- Color Palette Configuration Sections -->
      <div class="palette-cards-grid">
        <!-- General & Surface Colors -->
        <NCard class="panel-card" title="General & Canvas Colors" size="small">
              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Screen Background</span>
                  <span class="field-sub">Main terminal window backdrop</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.background"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.background"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Surface / Cards Background</span>
                  <span class="field-sub">Card panels, modals, surfaces</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.surface"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.surface"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Body Foreground Text</span>
                  <span class="field-sub">Default content text color</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.foreground"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.foreground"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Primary Brand Accent</span>
                  <span class="field-sub">Key highlights, buttons, badges</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.primary"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.primary"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Secondary Accent</span>
                  <span class="field-sub">Secondary emphasis</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.secondary"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.secondary"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>
            </NCard>

          <!-- Status Bars -->
          <NCard class="panel-card" title="Status Bars (Top & Bottom)" size="small">
              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Top Status Bar Background</span>
                  <span class="field-sub">Header bar background</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.status_bar_bg"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.status_bar_bg"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Model Name (Top Bar)</span>
                  <span class="field-sub">Active model label in header</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.status_bar_model"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.status_bar_model"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Token Info Text</span>
                  <span class="field-sub">Token usage stats</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.status_bar_tokens"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.status_bar_tokens"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Bottom Bar Background</span>
                  <span class="field-sub">Workspace shortcut status bar</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.bottom_bar_bg"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.bottom_bar_bg"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Session ID (Bottom Bar)</span>
                  <span class="field-sub">Active session ID highlight</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.bottom_bar_session"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.bottom_bar_session"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>
            </NCard>

          <!-- Input Area -->
          <NCard class="panel-card" title="Input Bar & Panels" size="small">
              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Prompt Bar Background</span>
                  <span class="field-sub">Input container dock background</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.prompt_bar_bg"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.prompt_bar_bg"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Prompt Symbol (&gt;)</span>
                  <span class="field-sub">Prompt cursor chevron symbol</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.prompt_symbol"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.prompt_symbol"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Input Field Text</span>
                  <span class="field-sub">User typed message color</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.input_text"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.input_text"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Todo Panel Text</span>
                  <span class="field-sub">Pinned plan checklist color</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.todo_text"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.todo_text"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>
            </NCard>

          <!-- Chat Output Area -->
          <NCard class="panel-card" title="Chat Log & Messages" size="small">
              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">User Message</span>
                  <span class="field-sub">User prompts and queries</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.user_msg"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.user_msg"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Assistant Message</span>
                  <span class="field-sub">Clanker responses</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.assistant_msg"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.assistant_msg"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Tool Card Accent</span>
                  <span class="field-sub">Tool invocation borders and titles</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.tool_card"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.tool_card"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Thinking Card Accent</span>
                  <span class="field-sub">Extended reasoning border</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.thinking_card"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.thinking_card"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>

              <div class="color-picker-row">
                <div class="color-label">
                  <span class="field-name">Hero Divider Rule</span>
                  <span class="field-sub">Horizontal rule below banner</span>
                </div>
                <div class="picker-controls">
                  <NColorPicker
                    v-model:value="currentTheme.palette.divider"
                    :show-alpha="false"
                    class="color-picker"
                    @update:value="markChanged"
                  />
                  <NInput
                    v-model:value="currentTheme.palette.divider"
                    size="small"
                    class="hex-input"
                    @update:value="markChanged"
                  />
                </div>
              </div>
            </NCard>

          <!-- Notifications & Alerts -->
          <NCard class="panel-card alerts-full-card" title="Alerts & Notification Levels" size="small">
            <div class="alerts-inner-grid">
              <div>
                <div class="color-picker-row">
                  <div class="color-label">
                    <span class="field-name">Success</span>
                    <span class="field-sub">Completed actions and positive badges</span>
                  </div>
                  <div class="picker-controls">
                    <NColorPicker
                      v-model:value="currentTheme.palette.notify_success"
                      :show-alpha="false"
                      class="color-picker"
                      @update:value="markChanged"
                    />
                    <NInput
                      v-model:value="currentTheme.palette.notify_success"
                      size="small"
                      class="hex-input"
                      @update:value="markChanged"
                    />
                  </div>
                </div>

                <div class="color-picker-row">
                  <div class="color-label">
                    <span class="field-name">Info</span>
                    <span class="field-sub">Informational notices and status</span>
                  </div>
                  <div class="picker-controls">
                    <NColorPicker
                      v-model:value="currentTheme.palette.notify_info"
                      :show-alpha="false"
                      class="color-picker"
                      @update:value="markChanged"
                    />
                    <NInput
                      v-model:value="currentTheme.palette.notify_info"
                      size="small"
                      class="hex-input"
                      @update:value="markChanged"
                    />
                  </div>
                </div>
              </div>

              <div>
                <div class="color-picker-row">
                  <div class="color-label">
                    <span class="field-name">Warning</span>
                    <span class="field-sub">Warnings and caution indicators</span>
                  </div>
                  <div class="picker-controls">
                    <NColorPicker
                      v-model:value="currentTheme.palette.notify_warning"
                      :show-alpha="false"
                      class="color-picker"
                      @update:value="markChanged"
                    />
                    <NInput
                      v-model:value="currentTheme.palette.notify_warning"
                      size="small"
                      class="hex-input"
                      @update:value="markChanged"
                    />
                  </div>
                </div>

                <div class="color-picker-row">
                  <div class="color-label">
                    <span class="field-name">Error</span>
                    <span class="field-sub">Failures, cancellations, and errors</span>
                  </div>
                  <div class="picker-controls">
                    <NColorPicker
                      v-model:value="currentTheme.palette.notify_error"
                      :show-alpha="false"
                      class="color-picker"
                      @update:value="markChanged"
                    />
                    <NInput
                      v-model:value="currentTheme.palette.notify_error"
                      size="small"
                      class="hex-input"
                      @update:value="markChanged"
                    />
                  </div>
                </div>
              </div>
            </div>
          </NCard>
        </div>
      </div>
    </NSpin>
  </div>
</template>

<style scoped>
.customization-panel {
  width: 100%;
}

.customization-stack {
  display: flex;
  flex-direction: column;
  gap: 24px;
  padding-bottom: 48px;
}

.palette-cards-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.alerts-full-card {
  grid-column: 1 / -1;
}

.alerts-inner-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24px;
}

.hero-card-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

@media (max-width: 900px) {
  .palette-cards-grid {
    grid-template-columns: 1fr;
  }
  .alerts-full-card {
    grid-column: auto;
  }
  .alerts-inner-grid {
    grid-template-columns: 1fr;
  }
  .hero-card-grid {
    grid-template-columns: 1fr;
  }
}

.section-intro {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 0;
  flex-wrap: wrap;
}

.intro-main h2 {
  font-size: 1.25rem;
  font-weight: 800;
  margin: 0 0 4px 0;
  letter-spacing: -0.02em;
}

.intro-desc {
  margin: 0;
  color: var(--nb-ink-muted);
  font-size: 0.875rem;
  max-width: 650px;
}

.intro-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.path-tag {
  font-family: monospace;
  font-size: 0.75rem;
  background: var(--nb-surface-inset);
  border: 1px solid var(--nb-border-subtle);
}

.panel-card {
  border: 2px solid var(--nb-border) !important;
  box-shadow: var(--nb-shadow-sm) !important;
  background: var(--nb-surface) !important;
  border-radius: 4px;
}

.card-hint {
  margin: 0 0 12px 0;
  font-size: 0.8125rem;
  color: var(--nb-ink-muted);
}

/* Presets Grid */
.presets-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}

.preset-item {
  border: 2px solid var(--nb-border-subtle);
  border-radius: 4px;
  padding: 10px 12px;
  cursor: pointer;
  background: var(--nb-surface-inset);
  transition: all 0.15s ease;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.preset-item:hover {
  border-color: var(--nb-pink);
  transform: translateY(-1px);
  box-shadow: 2px 2px 0 var(--nb-border);
}

.preset-item.active {
  border-color: var(--nb-lime);
  background: var(--nb-surface);
  box-shadow: 3px 3px 0 var(--nb-border);
}

.preset-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.preset-name {
  font-weight: 700;
  font-size: 0.8125rem;
}

.active-badge {
  font-size: 0.65rem;
  background: var(--nb-lime);
  color: #000;
  font-weight: 800;
  padding: 1px 4px;
  border-radius: 2px;
  letter-spacing: 0.05em;
}

.preset-desc {
  font-size: 0.72rem;
  color: var(--nb-ink-muted);
  margin: 0 0 8px 0;
  line-height: 1.3;
}

.preset-swatches {
  display: flex;
  gap: 4px;
}

.swatch {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  border: 1px solid rgba(0, 0, 0, 0.3);
}

/* Terminal Preview Mockup */
.preview-layout {
  border: 2px solid #000;
  border-radius: 6px;
  overflow: hidden;
  font-family: 'Victor Mono', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.preview-term-header {
  background: #1a1a24;
  padding: 6px 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.dot-red { background: #ff5f56; }
.dot-yellow { background: #ffbd2e; }
.dot-green { background: #27c93f; }

.term-title {
  color: #8b8b9e;
  font-size: 0.75rem;
  margin-left: 8px;
}

.preview-status-bar {
  padding: 4px 12px;
  font-size: 0.75rem;
  display: flex;
  align-items: center;
}

.preview-subagents {
  flex: 1;
  text-align: left;
}

.preview-tokens {
  flex: 0 0 auto;
  text-align: center;
}

.preview-model {
  flex: 1;
  text-align: right;
}

.preview-chat-viewport {
  padding: 0 16px 16px 16px;
  min-height: 240px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.ascii-art-block {
  margin: 0;
  font-size: 0.65rem;
  line-height: 1.25;
  letter-spacing: 0;
  font-weight: bold;
  overflow-x: auto;
}

.hero-status-line {
  font-size: 0.8125rem;
  margin-top: 8px;
}

.hero-model-line {
  font-size: 0.8125rem;
  margin-top: 2px;
}

.preview-rule {
  border-top: 2px solid;
  margin: 6px 0;
}

.preview-separator {
  border-top: 1px dashed;
  margin: 8px 0;
}

.preview-msg {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 0.8125rem;
}

.preview-msg p {
  margin: 0;
}

.msg-author {
  font-weight: 700;
  font-size: 0.75rem;
}

.preview-card-block {
  border-left: 3px solid;
  padding: 4px 10px;
  font-size: 0.78rem;
  border-radius: 0 3px 3px 0;
}

.code-line {
  font-family: monospace;
  margin-top: 2px;
}

.preview-input-area {
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
}

.preview-prompt-bar {
  padding: 6px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.preview-input-box {
  flex: 1;
  font-size: 0.8125rem;
  opacity: 0.6;
}

.preview-workspace-status {
  padding: 3px 12px;
  font-size: 0.72rem;
  display: flex;
  justify-content: space-between;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

/* Settings Form Controls */
.hero-art-group {
  height: 100%;
}

.mono-textarea {
  font-family: var(--font-mono, monospace);
  font-size: 0.72rem;
  line-height: 1.25;
  height: 275px;
}

:deep(.mono-textarea.n-input--textarea),
:deep(.mono-textarea .n-input-wrapper) {
  height: 100% !important;
}

:deep(.mono-textarea .n-input__textarea-el) {
  height: 100% !important;
  font-family: var(--font-mono, monospace) !important;
  font-size: 0.72rem !important;
  line-height: 1.25 !important;
  resize: none !important;
}

.setting-group {
  display: flex;
  flex-direction: column;
}

.setting-label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2px;
}

.setting-title {
  font-weight: 700;
  font-size: 0.875rem;
}

.setting-help {
  font-size: 0.78rem;
  color: var(--nb-ink-muted);
  margin: 0 0 12px 0;
  line-height: 1.4;
}

.field-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--nb-border-subtle);
  gap: 16px;
}

.field-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.field-name {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--nb-ink);
}

.field-sub {
  font-size: 0.72rem;
  color: var(--nb-ink-muted);
  line-height: 1.3;
}

.color-picker-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 0;
  border-bottom: 1px solid var(--nb-border-subtle);
  gap: 16px;
}

.color-picker-row:first-of-type {
  padding-top: 0;
}

.color-picker-row:last-of-type {
  border-bottom: none;
  padding-bottom: 0;
}

.color-label {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 2px;
}

.picker-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.color-picker {
  width: 34px !important;
  height: 34px !important;
  min-width: 34px !important;
  flex-shrink: 0;
}

:deep(.color-picker .n-color-picker-trigger) {
  width: 34px !important;
  height: 34px !important;
  min-width: 34px !important;
  padding: 0 !important;
  border-radius: 4px !important;
  border: 2px solid var(--nb-border) !important;
  overflow: hidden !important;
  box-shadow: 1.5px 1.5px 0 var(--nb-border);
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease;
}

:deep(.color-picker .n-color-picker-trigger:hover) {
  transform: translate(-1px, -1px);
  box-shadow: 2.5px 2.5px 0 var(--nb-border);
}

:deep(.color-picker .n-color-picker-trigger__fill) {
  left: 0 !important;
  right: 0 !important;
  top: 0 !important;
  bottom: 0 !important;
  border-radius: 2px !important;
}

:deep(.color-picker .n-color-picker-trigger__value) {
  display: none !important;
}

.hex-input {
  width: 100px !important;
  height: 34px !important;
}

:deep(.hex-input .n-input-wrapper) {
  height: 34px !important;
  padding-left: 6px !important;
  padding-right: 6px !important;
}

:deep(.hex-input .n-input__input-el) {
  font-family: var(--font-mono, monospace) !important;
  font-size: 0.8125rem !important;
  font-weight: 700 !important;
  text-align: center !important;
  letter-spacing: 0.05em !important;
  height: 34px !important;
  line-height: 34px !important;
}
</style>
