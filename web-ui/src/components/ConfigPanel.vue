<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import {
  NLayout,
  NLayoutSider,
  NLayoutContent,
  NMenu,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSwitch,
  NSlider,
  NButton,
  NSpace,
  NDivider,
  NTag,
  NDynamicTags,
  NAlert,
  NIcon,
  NSpin,
  NModal,
  NPopconfirm,
  NTooltip,
  NEmpty,
  useMessage,
} from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import {
  ShieldCheckmarkOutline,
  DocumentTextOutline,
  ExtensionPuzzleOutline,
  HardwareChipOutline,
  ColorPaletteOutline,
  AddOutline,
  CreateOutline,
  TrashOutline,
  PlayOutline,
  StarOutline,
  Star,
} from '@vicons/ionicons5'
import { h } from 'vue'

// Types
interface Config {
  agent: { name: string }
  safety: {
    require_confirmation: boolean
    sandbox_commands: boolean
    max_file_size: number
    command_timeout: number
    foreground_promote_after_seconds: number
    command_blacklist: string[]
  }
  output: {
    syntax_highlighting: boolean
    show_tool_calls: boolean
    stream_responses: boolean
    show_token_usage: boolean
  }
  context: {
    summarization_threshold: number
    keep_recent_turns: number
    max_tool_result_tokens: number
  }
  memory: {
    persist_sessions: boolean
    max_history_length: number
    storage_path: string
  }
  mcp: {
    enabled: boolean
    servers: Record<string, any>
  }
  logging: {
    enabled: boolean
    level: string
    max_file_size_mb: number
    backup_count: number
    console_output: boolean
    detailed_format: boolean
  }
}

interface ModelConfig {
  name: string
  provider: string
  api_key: string | null
  base_url: string | null
  model: string | null
  deployment_name: string | null
  api_version: string | null
  // Token limits
  max_tokens: number | null
  max_input_tokens: number | null
  // Extended thinking (Anthropic only)
  thinking_enabled: boolean
  thinking_budget_tokens: number
  // Reasoning effort (Azure OpenAI o1/o3 models)
  reasoning_effort: string | null
  // Streaming reliability (OpenAI/Azure): seconds to wait for next chunk
  stream_chunk_timeout: number | null
  // Cost tracking (USD per million tokens — optional, omit to skip cost display)
  cost_input: number | null
  cost_output: number | null
  cost_cache_read: number | null
  cost_cache_creation: number | null
}

// State
const message = useMessage()
const loading = ref(true)
const saving = ref(false)
const activeKey = ref('model')
const config = ref<Config | null>(null)
const configPath = ref('')
const hasChanges = ref(false)

// Models management
const models = ref<ModelConfig[]>([])
const defaultModel = ref<string | null>(null)

// GitHub Copilot connect flow
const copilotConnected = ref(false)
const copilotConnecting = ref(false)
const copilotSession = ref<{ sessionId: string; userCode: string; verificationUri: string } | null>(null)
let copilotPollTimer: ReturnType<typeof setInterval> | null = null
const modelsConfigPath = ref('')
const showModelModal = ref(false)
const editingModel = ref<string | null>(null)
const testingModel = ref<string | null>(null)
const savingModel = ref(false)
const modelForm = ref<ModelConfig>({
  name: '',
  provider: 'OpenAI',
  api_key: null,
  base_url: null,
  model: null,
  deployment_name: null,
  api_version: null,
  max_tokens: null,
  max_input_tokens: null,
  thinking_enabled: false,
  thinking_budget_tokens: 10000,
  reasoning_effort: null,
  stream_chunk_timeout: null,
  cost_input: null,
  cost_output: null,
  cost_cache_read: null,
  cost_cache_creation: null,
})

// MCP Server editing
const showMcpModal = ref(false)
const editingMcpServer = ref<string | null>(null)
const mcpForm = ref({
  name: '',
  transport: 'stdio' as 'stdio' | 'sse',
  command: '',
  args: '',
  env: '',
  url: '',
  enabled: true,
})
const testingServer = ref<string | null>(null)

// Menu items
const menuOptions: MenuOption[] = [
  { label: 'Models', key: 'model', icon: () => h(NIcon, null, { default: () => h(HardwareChipOutline) }) },
  { label: 'Context', key: 'context', icon: () => h(NIcon, null, { default: () => h(ColorPaletteOutline) }) },
  { label: 'Safety', key: 'safety', icon: () => h(NIcon, null, { default: () => h(ShieldCheckmarkOutline) }) },
  { label: 'MCP Servers', key: 'mcp', icon: () => h(NIcon, null, { default: () => h(ExtensionPuzzleOutline) }) },
  { label: 'Logging', key: 'logging', icon: () => h(NIcon, null, { default: () => h(DocumentTextOutline) }) },
]

// Provider options for model config
const modelProviderOptions = [
  { label: 'OpenAI', value: 'OpenAI', description: 'GPT-4, GPT-4o, etc.' },
  { label: 'Azure OpenAI', value: 'AzureOpenAI', description: 'OpenAI models on Azure' },
  { label: 'Anthropic', value: 'Anthropic', description: 'Claude models' },
  { label: 'Ollama', value: 'Ollama', description: 'Local models via Ollama' },
  { label: 'GitHub Copilot', value: 'GitHubCopilot', description: 'Auto-configured via Connect below' },
]

// Provider colors and icons for visual distinction (neon palette)
const providerStyles: Record<string, { color: string; bgColor: string }> = {
  'OpenAI': { color: '#b6ff1a', bgColor: 'rgba(182, 255, 26, 0.12)' },
  'AzureOpenAI': { color: '#00f0ff', bgColor: 'rgba(0, 240, 255, 0.12)' },
  'Anthropic': { color: '#ff2bd6', bgColor: 'rgba(255, 43, 214, 0.12)' },
  'Ollama': { color: '#ffe600', bgColor: 'rgba(255, 230, 0, 0.12)' },
  'GitHubCopilot': { color: '#8957e5', bgColor: 'rgba(137, 87, 229, 0.12)' },
}

const logLevelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'CRITICAL', value: 'CRITICAL' },
]

// Model form computed
const isModelFormAzure = computed(() => modelForm.value.provider === 'AzureOpenAI')
const isModelFormOpenAI = computed(() => modelForm.value.provider === 'OpenAI')
const isModelFormAnthropic = computed(() => modelForm.value.provider === 'Anthropic')
const isModelFormOllama = computed(() => modelForm.value.provider === 'Ollama')

// Get placeholder for model ID based on provider
const modelIdPlaceholder = computed(() => {
  switch (modelForm.value.provider) {
    case 'OpenAI': return 'e.g., gpt-4o, gpt-4-turbo'
    case 'AzureOpenAI': return 'Leave empty if using deployment name'
    case 'Anthropic': return 'e.g., claude-sonnet-4-20250514'
    case 'Ollama': return 'e.g., llama3, mistral, codellama'
    default: return 'Model identifier'
  }
})

// API functions
async function fetchConfig() {
  try {
    const response = await fetch('/api/config')
    const data = await response.json()
    config.value = data.config
    configPath.value = data.config_path
  } catch (error) {
    message.error('Failed to load configuration')
    console.error(error)
  } finally {
    loading.value = false
  }
}

// Models API functions
async function fetchModels() {
  try {
    const response = await fetch('/api/models')
    const data = await response.json()
    models.value = data.models
    defaultModel.value = data.default
    modelsConfigPath.value = data.config_path
  } catch (error) {
    console.error('Failed to load models:', error)
  }
}

// GitHub Copilot connect flow
async function fetchCopilotStatus() {
  try {
    const response = await fetch('/api/copilot/status')
    const data = await response.json()
    copilotConnected.value = data.connected
  } catch (error) {
    console.error('Failed to load Copilot status:', error)
  }
}

function stopCopilotPolling() {
  if (copilotPollTimer !== null) {
    clearInterval(copilotPollTimer)
    copilotPollTimer = null
  }
}

async function startCopilotLogin() {
  copilotConnecting.value = true
  copilotSession.value = null
  try {
    const response = await fetch('/api/copilot/login/start', { method: 'POST' })
    if (!response.ok) {
      const err = await response.json()
      message.error(err.detail || 'Failed to start GitHub Copilot login')
      copilotConnecting.value = false
      return
    }
    const data = await response.json()
    copilotSession.value = {
      sessionId: data.session_id,
      userCode: data.user_code,
      verificationUri: data.verification_uri,
    }
    // Poll every 3s -- generous relative to GitHub's device-flow interval
    // (typically 5s), avoids hammering the endpoint while staying responsive.
    copilotPollTimer = setInterval(pollCopilotLogin, 3000)
  } catch (error) {
    message.error('Failed to start GitHub Copilot login')
    console.error(error)
    copilotConnecting.value = false
  }
}

async function pollCopilotLogin() {
  if (!copilotSession.value) return
  try {
    const response = await fetch('/api/copilot/login/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: copilotSession.value.sessionId }),
    })
    const data = await response.json()

    if (data.status === 'pending') {
      return
    }

    stopCopilotPolling()
    copilotConnecting.value = false
    copilotSession.value = null

    if (data.status === 'success') {
      copilotConnected.value = true
      message.success(`Connected! Synced ${data.models_synced} Copilot model(s).`)
      await fetchModels()
    } else if (data.status === 'expired') {
      message.warning('GitHub Copilot login code expired. Try again.')
    } else {
      message.error(data.detail || 'GitHub Copilot login failed.')
    }
  } catch (error) {
    stopCopilotPolling()
    copilotConnecting.value = false
    message.error('Lost connection while waiting for GitHub Copilot login.')
    console.error(error)
  }
}

async function refreshCopilotModels() {
  try {
    const response = await fetch('/api/copilot/refresh-models', { method: 'POST' })
    if (!response.ok) {
      const err = await response.json()
      message.error(err.detail || 'Failed to refresh Copilot models')
      return
    }
    const data = await response.json()
    message.success(`Synced ${data.models_synced} Copilot model(s).`)
    await fetchModels()
  } catch (error) {
    message.error('Failed to refresh Copilot models')
    console.error(error)
  }
}

function cancelCopilotLogin() {
  stopCopilotPolling()
  copilotConnecting.value = false
  copilotSession.value = null
}

function openAddModel() {
  editingModel.value = null
  modelForm.value = {
    name: '',
    provider: 'OpenAI',
    api_key: null,
    base_url: null,
    model: null,
    deployment_name: null,
    api_version: null,
    max_tokens: null,
    max_input_tokens: null,
    thinking_enabled: false,
    thinking_budget_tokens: 10000,
    reasoning_effort: null,
    stream_chunk_timeout: null,
    cost_input: null,
    cost_output: null,
    cost_cache_read: null,
    cost_cache_creation: null,
  }
  showModelModal.value = true
}

function openEditModel(model: ModelConfig) {
  editingModel.value = model.name
  modelForm.value = { ...model }
  showModelModal.value = true
}

async function saveModel() {
  if (!modelForm.value.name.trim()) {
    message.error('Model name is required')
    return
  }

  savingModel.value = true
  try {
    const url = editingModel.value
      ? `/api/models/${encodeURIComponent(editingModel.value)}`
      : '/api/models'
    const method = editingModel.value ? 'PUT' : 'POST'

    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(modelForm.value),
    })

    if (response.ok) {
      message.success(editingModel.value ? 'Model updated' : 'Model added')
      showModelModal.value = false
      await fetchModels()
    } else {
      const error = await response.json()
      message.error(error.detail || 'Failed to save model')
    }
  } catch (error) {
    message.error('Failed to save model')
    console.error(error)
  } finally {
    savingModel.value = false
  }
}

async function deleteModel(name: string) {
  try {
    const response = await fetch(`/api/models/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    })

    if (response.ok) {
      message.success('Model deleted')
      await fetchModels()
    } else {
      const error = await response.json()
      message.error(error.detail || 'Failed to delete model')
    }
  } catch (error) {
    message.error('Failed to delete model')
    console.error(error)
  }
}

async function setAsDefault(name: string) {
  try {
    const response = await fetch('/api/models/default', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })

    if (response.ok) {
      message.success(`${name} set as default`)
      defaultModel.value = name
    } else {
      const error = await response.json()
      message.error(error.detail || 'Failed to set default model')
    }
  } catch (error) {
    message.error('Failed to set default model')
    console.error(error)
  }
}

async function testModel(name: string) {
  testingModel.value = name
  try {
    const response = await fetch(`/api/models/${encodeURIComponent(name)}/test`, {
      method: 'POST',
    })

    if (response.ok) {
      const data = await response.json()
      message.success(data.message)
    } else {
      const error = await response.json()
      message.error(error.detail || 'Connection test failed')
    }
  } catch (error) {
    message.error('Connection test failed')
    console.error(error)
  } finally {
    testingModel.value = null
  }
}

function getProviderStyle(provider: string) {
  return providerStyles[provider] || { color: '#888', bgColor: 'rgba(136, 136, 136, 0.1)' }
}

async function saveConfig() {
  if (!config.value) return

  saving.value = true
  try {
    const response = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: config.value }),
    })

    if (response.ok) {
      message.success('Configuration saved')
      hasChanges.value = false
    } else {
      const error = await response.json()
      message.error(error.detail || 'Failed to save configuration')
    }
  } catch (error) {
    message.error('Failed to save configuration')
    console.error(error)
  } finally {
    saving.value = false
  }
}

async function resetConfig() {
  if (!confirm('Reset all settings to defaults?')) return

  try {
    const response = await fetch('/api/config/reset', { method: 'POST' })
    if (response.ok) {
      message.success('Configuration reset to defaults')
      await fetchConfig()
      hasChanges.value = false
    } else {
      message.error('Failed to reset configuration')
    }
  } catch (error) {
    message.error('Failed to reset configuration')
  }
}

function markChanged() {
  hasChanges.value = true
}

// MCP Server management
function openAddMcpServer() {
  editingMcpServer.value = null
  mcpForm.value = {
    name: '',
    transport: 'stdio',
    command: '',
    args: '',
    env: '',
    url: '',
    enabled: true,
  }
  showMcpModal.value = true
}

function openEditMcpServer(name: string) {
  if (!config.value) return
  const server = config.value.mcp.servers[name]
  editingMcpServer.value = name
  mcpForm.value = {
    name: name,
    transport: server.transport || 'stdio',
    command: server.command || '',
    args: (server.args || []).join(' '),
    env: Object.entries(server.env || {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    url: server.url || '',
    enabled: server.enabled !== false,
  }
  showMcpModal.value = true
}

function saveMcpServer() {
  if (!config.value || !mcpForm.value.name.trim()) {
    message.error('Server name is required')
    return
  }

  const name = mcpForm.value.name.trim()

  // Parse args (space-separated)
  const args = mcpForm.value.args.trim()
    ? mcpForm.value.args.trim().split(/\s+/)
    : []

  // Parse env (KEY=VALUE per line)
  const env: Record<string, string> = {}
  if (mcpForm.value.env.trim()) {
    mcpForm.value.env.trim().split('\n').forEach(line => {
      const [key, ...rest] = line.split('=')
      if (key && rest.length > 0) {
        env[key.trim()] = rest.join('=').trim()
      }
    })
  }

  const serverConfig: any = {
    transport: mcpForm.value.transport,
    enabled: mcpForm.value.enabled,
  }

  if (mcpForm.value.transport === 'stdio') {
    serverConfig.command = mcpForm.value.command
    serverConfig.args = args
    serverConfig.env = env
  } else {
    serverConfig.url = mcpForm.value.url
  }

  // If renaming, delete old key
  if (editingMcpServer.value && editingMcpServer.value !== name) {
    delete config.value.mcp.servers[editingMcpServer.value]
  }

  config.value.mcp.servers[name] = serverConfig
  showMcpModal.value = false
  markChanged()
  message.success(editingMcpServer.value ? 'Server updated' : 'Server added')
}

function deleteMcpServer(name: string) {
  if (!config.value) return
  delete config.value.mcp.servers[name]
  markChanged()
  message.success('Server deleted')
}

async function testMcpServer(name: string) {
  if (!config.value) return
  const server = config.value.mcp.servers[name]

  testingServer.value = name
  try {
    const response = await fetch('/api/mcp/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(server),
    })

    if (response.ok) {
      const data = await response.json()
      message.success(`${name}: ${data.message}`)
    } else {
      const error = await response.json()
      message.error(`${name}: ${error.detail}`)
    }
  } catch (error) {
    message.error(`${name}: Connection test failed`)
  } finally {
    testingServer.value = null
  }
}

onMounted(() => {
  fetchConfig()
  fetchModels()
  fetchCopilotStatus()
})

onUnmounted(() => {
  stopCopilotPolling()
})
</script>

<template>
  <NLayout class="app-layout" has-sider>
    <!-- Sidebar -->
    <NLayoutSider
      bordered
      :width="200"
      :native-scrollbar="false"
      class="sidebar"
    >
      <div class="logo">
        <span class="logo-icon">⚙️</span>
        <span class="logo-text">CLANKER</span>
      </div>
      <NMenu
        v-model:value="activeKey"
        :options="menuOptions"
        :root-indent="20"
      />
    </NLayoutSider>

    <!-- Main Content -->
    <NLayoutContent class="main-content">
      <NSpin :show="loading">
        <div v-if="config" class="content-wrapper">
          <!-- Header -->
          <div class="content-header">
            <h1>{{ activeKey === 'model' ? 'Models' : menuOptions.find(m => m.key === activeKey)?.label + ' Settings' }}</h1>
            <NSpace>
              <NButton
                v-if="hasChanges"
                type="primary"
                :loading="saving"
                @click="saveConfig"
              >
                Save Changes
              </NButton>
              <NButton v-if="activeKey !== 'model'" quaternary @click="resetConfig">Reset to Defaults</NButton>
            </NSpace>
          </div>

          <NDivider />

          <!-- Model Settings - New Card-based UI -->
          <div v-if="activeKey === 'model'" class="models-section">
            <!-- Header with Add button -->
            <div class="models-header">
              <div class="models-header-text">
                <p class="models-description">
                  Configure your LLM providers. Models are stored in <code>~/.clanker/models.json</code>
                </p>
              </div>
              <NButton type="primary" @click="openAddModel">
                <template #icon>
                  <NIcon><AddOutline /></NIcon>
                </template>
                Add Model
              </NButton>
            </div>

            <!-- GitHub Copilot Connect -->
            <NCard class="copilot-card" :style="{ borderColor: providerStyles['GitHubCopilot'].color + '40' }">
              <div class="copilot-card-content">
                <div class="copilot-card-info">
                  <NTag
                    size="small"
                    :color="{ color: providerStyles['GitHubCopilot'].bgColor, textColor: providerStyles['GitHubCopilot'].color, borderColor: 'transparent' }"
                  >
                    GitHub Copilot
                  </NTag>
                  <span v-if="copilotConnected" class="copilot-status-text">
                    Connected — models sync automatically as <code>copilot:&lt;model&gt;</code>
                  </span>
                  <span v-else-if="copilotSession" class="copilot-status-text">
                    Open <a :href="copilotSession.verificationUri" target="_blank" rel="noopener">{{ copilotSession.verificationUri }}</a>
                    and enter code <strong class="copilot-user-code">{{ copilotSession.userCode }}</strong>
                  </span>
                  <span v-else class="copilot-status-text">
                    Connect your existing GitHub Copilot subscription to use its models directly — no separate proxy required.
                  </span>
                </div>
                <NSpace>
                  <NButton v-if="copilotSession" quaternary @click="cancelCopilotLogin">Cancel</NButton>
                  <NButton v-if="copilotConnected" size="small" @click="refreshCopilotModels">Refresh Models</NButton>
                  <NButton
                    v-else
                    type="primary"
                    :loading="copilotConnecting"
                    :disabled="!!copilotSession"
                    @click="startCopilotLogin"
                  >
                    Connect GitHub Copilot
                  </NButton>
                </NSpace>
              </div>
            </NCard>

            <!-- Models Grid -->
            <div v-if="models.length > 0" class="models-grid">
              <NCard
                v-for="model in models"
                :key="model.name"
                class="model-card"
                :class="{ 'model-card-default': model.name === defaultModel }"
                :style="{ borderColor: getProviderStyle(model.provider).color + '40' }"
              >
                <!-- Card Header -->
                <template #header>
                  <div class="model-card-header">
                    <div class="model-info">
                      <NTag
                        size="small"
                        :color="{ color: getProviderStyle(model.provider).bgColor, textColor: getProviderStyle(model.provider).color, borderColor: 'transparent' }"
                      >
                        {{ model.provider }}
                      </NTag>
                      <span class="model-name">{{ model.name }}</span>
                      <NTooltip v-if="model.name === defaultModel">
                        <template #trigger>
                          <NIcon class="default-star" :component="Star" />
                        </template>
                        Default Model
                      </NTooltip>
                    </div>
                  </div>
                </template>

                <!-- Card Content -->
                <div class="model-details">
                  <div v-if="model.model" class="model-detail-row">
                    <span class="detail-label">Model ID:</span>
                    <code class="detail-value">{{ model.model }}</code>
                  </div>
                  <div v-if="model.deployment_name" class="model-detail-row">
                    <span class="detail-label">Deployment:</span>
                    <code class="detail-value">{{ model.deployment_name }}</code>
                  </div>
                  <div v-if="model.base_url" class="model-detail-row">
                    <span class="detail-label">Base URL:</span>
                    <code class="detail-value detail-url">{{ model.base_url }}</code>
                  </div>
                  <div class="model-detail-row">
                    <span class="detail-label">API Key:</span>
                    <code class="detail-value">{{ model.api_key || '(from environment)' }}</code>
                  </div>
                  <div v-if="model.max_tokens" class="model-detail-row">
                    <span class="detail-label">Max Tokens:</span>
                    <code class="detail-value">{{ model.max_tokens?.toLocaleString() }}</code>
                  </div>
                  <div v-if="model.max_input_tokens" class="model-detail-row">
                    <span class="detail-label">Max Input:</span>
                    <code class="detail-value">{{ model.max_input_tokens?.toLocaleString() }}</code>
                  </div>
                  <div v-if="model.thinking_enabled" class="model-detail-row">
                    <span class="detail-label">Thinking:</span>
                    <NTag size="small" type="info">{{ model.thinking_budget_tokens?.toLocaleString() }} tokens</NTag>
                  </div>
                  <div v-if="model.reasoning_effort" class="model-detail-row">
                    <span class="detail-label">Reasoning:</span>
                    <NTag size="small" type="warning">{{ model.reasoning_effort }}</NTag>
                  </div>
                  <div v-if="model.cost_input != null || model.cost_output != null" class="model-detail-row">
                    <span class="detail-label">Pricing:</span>
                    <span class="detail-value" style="font-size: 0.82em; color: var(--n-text-color-3)">
                      <template v-if="model.cost_input != null">in ${{ model.cost_input }}/M</template>
                      <template v-if="model.cost_input != null && model.cost_output != null"> · </template>
                      <template v-if="model.cost_output != null">out ${{ model.cost_output }}/M</template>
                      <template v-if="model.cost_cache_read != null"> · cache ${{ model.cost_cache_read }}/M</template>
                    </span>
                  </div>
                </div>

                <!-- Card Actions -->
                <template #footer>
                  <NSpace justify="space-between" align="center">
                    <NSpace>
                      <NButton
                        size="small"
                        :loading="testingModel === model.name"
                        @click="testModel(model.name)"
                      >
                        <template #icon>
                          <NIcon><PlayOutline /></NIcon>
                        </template>
                        Test
                      </NButton>
                      <NButton
                        v-if="model.name !== defaultModel"
                        size="small"
                        @click="setAsDefault(model.name)"
                      >
                        <template #icon>
                          <NIcon><StarOutline /></NIcon>
                        </template>
                        Set Default
                      </NButton>
                    </NSpace>
                    <NSpace>
                      <NButton size="small" @click="openEditModel(model)">
                        <template #icon>
                          <NIcon><CreateOutline /></NIcon>
                        </template>
                        Edit
                      </NButton>
                      <NPopconfirm @positive-click="deleteModel(model.name)">
                        <template #trigger>
                          <NButton size="small" type="error" quaternary>
                            <template #icon>
                              <NIcon><TrashOutline /></NIcon>
                            </template>
                          </NButton>
                        </template>
                        Delete "{{ model.name }}"?
                      </NPopconfirm>
                    </NSpace>
                  </NSpace>
                </template>
              </NCard>
            </div>

            <!-- Empty State -->
            <NCard v-else class="empty-models-card">
              <NEmpty description="No models configured">
                <template #extra>
                  <NButton type="primary" @click="openAddModel">
                    <template #icon>
                      <NIcon><AddOutline /></NIcon>
                    </template>
                    Add Your First Model
                  </NButton>
                </template>
              </NEmpty>
            </NCard>

            <!-- Legacy Settings Info -->
            <NAlert type="info" style="margin-top: 16px">
              <strong>Note:</strong> If no models are configured above, Clanker falls back to settings in
              <code>config.yaml</code>. Add models here for easier switching with the <code>/model</code> command.
            </NAlert>
          </div>

          <!-- Add/Edit Model Modal -->
          <NModal
            v-model:show="showModelModal"
            preset="card"
            :title="editingModel ? 'Edit Model' : 'Add Model'"
            style="width: 550px"
          >
            <NForm label-placement="left" label-width="120">
              <NFormItem label="Display Name" required>
                <NInput
                  v-model:value="modelForm.name"
                  placeholder="e.g., GPT-4o, Claude Sonnet, My Azure Model"
                />
              </NFormItem>

              <NFormItem label="Provider" required>
                <NSelect
                  v-model:value="modelForm.provider"
                  :options="modelProviderOptions"
                />
              </NFormItem>

              <NDivider style="margin: 16px 0">Connection Settings</NDivider>

              <NFormItem label="Model ID">
                <NInput
                  v-model:value="modelForm.model"
                  :placeholder="modelIdPlaceholder"
                />
              </NFormItem>

              <template v-if="isModelFormAzure">
                <NFormItem label="Deployment Name" required>
                  <NInput
                    v-model:value="modelForm.deployment_name"
                    placeholder="Your Azure deployment name"
                  />
                </NFormItem>

                <NFormItem label="API Version">
                  <NInput
                    v-model:value="modelForm.api_version"
                    placeholder="2024-02-15-preview"
                  />
                </NFormItem>
              </template>

              <NFormItem label="Max Tokens">
                <NInputNumber
                  v-model:value="modelForm.max_tokens"
                  :min="1"
                  placeholder="Default (4096 for Anthropic)"
                  clearable
                  style="width: 100%"
                />
              </NFormItem>

              <NFormItem label="Max Input Tokens">
                <NInputNumber
                  v-model:value="modelForm.max_input_tokens"
                  :min="1"
                  placeholder="Required for OpenRouter/custom endpoints"
                  clearable
                  style="width: 100%"
                />
              </NFormItem>

              <NFormItem label="Base URL">
                <NInput
                  v-model:value="modelForm.base_url"
                  :placeholder="isModelFormAzure ? 'https://your-resource.openai.azure.com' : isModelFormOllama ? 'http://localhost:11434' : 'Leave empty for default'"
                />
              </NFormItem>

              <NFormItem label="API Key">
                <NInput
                  v-model:value="modelForm.api_key"
                  type="password"
                  show-password-on="click"
                  :placeholder="isModelFormOllama ? 'Not required for Ollama' : 'Leave empty to use environment variable'"
                />
              </NFormItem>

              <NAlert v-if="!isModelFormOllama" type="info" style="margin-top: 8px">
                <small>
                  <strong>Tip:</strong> You can leave API Key empty to use environment variables
                  ({{ modelForm.provider === 'OpenAI' ? 'OPENAI_API_KEY' : modelForm.provider === 'AzureOpenAI' ? 'AZURE_OPENAI_API_KEY' : 'ANTHROPIC_API_KEY' }}).
                </small>
              </NAlert>

              <!-- Reasoning Effort (OpenAI o1/o3/GPT-5+ models) -->
              <template v-if="isModelFormAzure || isModelFormOpenAI">
                <NDivider style="margin: 16px 0">Reasoning (o1/o3/GPT-5+ models)</NDivider>

                <NFormItem label="Reasoning Effort">
                  <NSelect
                    v-model:value="modelForm.reasoning_effort"
                    :options="[
                      { label: 'None (disabled)', value: null },
                      { label: 'Minimal', value: 'minimal' },
                      { label: 'Low', value: 'low' },
                      { label: 'Medium', value: 'medium' },
                      { label: 'High', value: 'high' },
                      { label: 'Extra High (GPT-5.1+)', value: 'xhigh' },
                    ]"
                    clearable
                    placeholder="Select reasoning effort"
                  />
                </NFormItem>

                <NAlert v-if="modelForm.reasoning_effort" type="info" style="margin-top: 8px">
                  <small>
                    Reasoning effort controls how much the model "thinks" before responding.
                    Works with o1, o3, GPT-5, and newer reasoning-capable models.
                    "xhigh" is only supported for models after GPT-5.1.
                  </small>
                </NAlert>

                <NDivider style="margin: 16px 0">Streaming</NDivider>

                <NFormItem label="Stream Chunk Timeout (s)">
                  <NInputNumber
                    v-model:value="modelForm.stream_chunk_timeout"
                    :min="0"
                    placeholder="Default 600s (0 disables)"
                    clearable
                    style="width: 100%"
                  />
                </NFormItem>

                <NAlert type="info" style="margin-top: 8px">
                  <small>
                    Max seconds to wait for the next streamed chunk before erroring. Raise this
                    for high-reasoning models that pause silently while thinking. Leave empty for
                    the default ({{ 600 }}s); set to <strong>0</strong> to disable entirely.
                  </small>
                </NAlert>
              </template>

              <!-- Extended Thinking (Anthropic only) -->
              <template v-if="isModelFormAnthropic">
                <NDivider style="margin: 16px 0">Extended Thinking</NDivider>

                <NFormItem label="Enable Thinking">
                  <NSwitch v-model:value="modelForm.thinking_enabled" />
                </NFormItem>

                <NFormItem v-if="modelForm.thinking_enabled" label="Budget Tokens">
                  <NInputNumber
                    v-model:value="modelForm.thinking_budget_tokens"
                    :min="1"
                    :step="1000"
                    style="width: 100%"
                  />
                </NFormItem>

                <NAlert v-if="modelForm.thinking_enabled" type="warning" style="margin-top: 8px">
                  <small>
                    Extended thinking allows the model to reason through complex problems.
                    <strong>Max Tokens must be greater than Budget Tokens.</strong>
                    If not set, it defaults to Budget + 16,000.
                  </small>
                </NAlert>
              </template>

              <!-- Cost Tracking -->
              <NDivider style="margin: 16px 0">Cost Tracking (optional)</NDivider>
              <NAlert type="info" style="margin-bottom: 12px">
                <small>
                  Enter your model's pricing in <strong>USD per million tokens</strong>.
                  When set, Clanker shows the estimated cost after each response.
                  Leave all fields empty to skip cost tracking.
                  You can find pricing on your provider's pricing page (e.g. <a href="https://openai.com/pricing" target="_blank" rel="noopener">openai.com/pricing</a>).
                </small>
              </NAlert>

              <NFormItem label="Input ($/M tokens)">
                <NInputNumber
                  v-model:value="modelForm.cost_input"
                  :min="0"
                  :precision="6"
                  :step="0.1"
                  placeholder="e.g. 2.50"
                  clearable
                  style="width: 100%"
                />
              </NFormItem>

              <NFormItem label="Output ($/M tokens)">
                <NInputNumber
                  v-model:value="modelForm.cost_output"
                  :min="0"
                  :precision="6"
                  :step="0.1"
                  placeholder="e.g. 10.00"
                  clearable
                  style="width: 100%"
                />
              </NFormItem>

              <NFormItem label="Cache Read ($/M)">
                <NInputNumber
                  v-model:value="modelForm.cost_cache_read"
                  :min="0"
                  :precision="6"
                  :step="0.01"
                  placeholder="e.g. 0.30 (Anthropic cache read)"
                  clearable
                  style="width: 100%"
                />
              </NFormItem>

              <NFormItem label="Cache Write ($/M)">
                <NInputNumber
                  v-model:value="modelForm.cost_cache_creation"
                  :min="0"
                  :precision="6"
                  :step="0.01"
                  placeholder="e.g. 3.75 (Anthropic cache write)"
                  clearable
                  style="width: 100%"
                />
              </NFormItem>
            </NForm>

            <template #footer>
              <NSpace justify="end">
                <NButton @click="showModelModal = false">Cancel</NButton>
                <NButton type="primary" :loading="savingModel" @click="saveModel">
                  {{ editingModel ? 'Update' : 'Add Model' }}
                </NButton>
              </NSpace>
            </template>
          </NModal>

          <!-- API Keys, Output, Memory, Agent tabs removed:
               - API Keys: informational only (env var display)
               - Output.stream_responses was dead; rest moved out of UI
               - Memory: persist_sessions/max_history_length were dead; storage_path is read-only
               - Agent.name was barely used; removed to simplify -->

          <!-- Context Settings -->
          <NCard v-if="activeKey === 'context'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Compaction Threshold">
                <NSlider
                  v-model:value="config.context.summarization_threshold"
                  :min="50"
                  :max="99"
                  :step="1"
                  :format-tooltip="(v: number) => `${v}%`"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Keep Recent Turns">
                <NInputNumber
                  v-model:value="config.context.keep_recent_turns"
                  :min="1"
                  :max="20"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Max Tool Result Tokens">
                <NInputNumber
                  v-model:value="config.context.max_tool_result_tokens"
                  :min="0"
                  :step="1000"
                  style="width: 100%"
                  @update:value="markChanged"
                />
              </NFormItem>
              <div class="form-hint">
                Caps any single tool result (file reads, command output, MCP
                tools) to this many tokens. Oversized results are truncated at
                the tool boundary so one large output cannot overflow the
                context window. Set to <strong>0</strong> to disable truncation.
              </div>
            </NForm>
          </NCard>

          <!-- Safety Settings -->
          <NCard v-if="activeKey === 'safety'" class="settings-card">
            <NAlert type="info" style="margin-bottom: 16px">
              <strong>Require Confirmation:</strong> prompts you before every bash command (bypassed by <code>--yolo</code>).<br />
              <strong>Sandbox Commands:</strong> blocks dangerous commands (<code>rm -rf /</code>, fork bombs, etc.) before they reach the shell.
            </NAlert>

            <NForm label-placement="left" label-width="200">
              <NFormItem label="Require Confirmation">
                <NSwitch
                  v-model:value="config.safety.require_confirmation"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Sandbox Commands">
                <NSwitch
                  v-model:value="config.safety.sandbox_commands"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Max File Size (bytes)">
                <NInputNumber
                  v-model:value="config.safety.max_file_size"
                  :min="1000"
                  style="width: 100%"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Command Timeout (ms)">
                <NInputNumber
                  v-model:value="config.safety.command_timeout"
                  :min="1000"
                  style="width: 100%"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Auto-promote to Background (s)">
                <NInputNumber
                  v-model:value="config.safety.foreground_promote_after_seconds"
                  :min="0"
                  style="width: 100%"
                  @update:value="markChanged"
                />
              </NFormItem>
              <div class="form-hint">
                Foreground <code>execute_shell</code> commands running longer
                than this threshold are auto-promoted to a background job, so
                the agent can keep working and poll progress with
                <code>bash_status</code> / <code>bash_output</code>. Set to
                <strong>0</strong> to disable promotion (legacy blocking
                behavior).
              </div>

              <NFormItem label="Command Blacklist" :label-style="{ alignItems: 'flex-start' }">
                <NDynamicTags
                  v-model:value="config.safety.command_blacklist"
                  @update:value="markChanged"
                />
              </NFormItem>
              <div class="form-hint">
                Commands the agent must never run. Case-insensitive
                <strong>substring</strong> match, so <code>git push</code> blocks
                <code>git push origin main</code>. Applied on top of the built-in
                blocks and only while <strong>Sandbox Commands</strong> is on.
                A project can add more bans via a <code>.clanker/blacklist</code>
                file (one entry per line); those are merged with this list.
              </div>
            </NForm>
          </NCard>

          <!-- Memory tab removed (all toggles were dead, storage_path is read-only) -->

          <!-- MCP Settings -->
          <NCard v-if="activeKey === 'mcp'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Enable MCP">
                <NSwitch
                  v-model:value="config.mcp.enabled"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NDivider>
                <NSpace>
                  Configured Servers
                  <NButton size="small" type="primary" @click="openAddMcpServer">
                    + Add Server
                  </NButton>
                </NSpace>
              </NDivider>

              <div v-if="Object.keys(config.mcp.servers).length === 0" class="empty-state">
                No MCP servers configured. Click "Add Server" to add one.
              </div>

              <div v-else class="mcp-servers">
                <NCard v-for="(server, name) in config.mcp.servers" :key="name" size="small">
                  <template #header>
                    <NSpace align="center" justify="space-between" style="width: 100%">
                      <NSpace align="center">
                        <NTag :type="server.enabled !== false ? 'success' : 'default'" size="small">
                          {{ server.enabled !== false ? 'Enabled' : 'Disabled' }}
                        </NTag>
                        <strong>{{ name }}</strong>
                      </NSpace>
                      <NSpace>
                        <NButton
                          size="tiny"
                          type="info"
                          :loading="testingServer === String(name)"
                          @click="testMcpServer(String(name))"
                        >
                          Test
                        </NButton>
                        <NButton size="tiny" @click="openEditMcpServer(String(name))">Edit</NButton>
                        <NPopconfirm @positive-click="deleteMcpServer(String(name))">
                          <template #trigger>
                            <NButton size="tiny" type="error">Delete</NButton>
                          </template>
                          Delete server "{{ name }}"?
                        </NPopconfirm>
                      </NSpace>
                    </NSpace>
                  </template>
                  <code>{{ server.transport }}: {{ server.command || server.url }}</code>
                  <div v-if="server.args?.length" class="server-detail">
                    <small>Args: {{ server.args.join(' ') }}</small>
                  </div>
                </NCard>
              </div>
            </NForm>
          </NCard>

          <!-- MCP Server Modal -->
          <NModal
            v-model:show="showMcpModal"
            preset="card"
            :title="editingMcpServer ? 'Edit MCP Server' : 'Add MCP Server'"
            style="width: 500px"
          >
            <NForm label-placement="left" label-width="100">
              <NFormItem label="Name" required>
                <NInput
                  v-model:value="mcpForm.name"
                  placeholder="e.g., filesystem, github"
                />
              </NFormItem>

              <NFormItem label="Transport">
                <NSelect
                  v-model:value="mcpForm.transport"
                  :options="[
                    { label: 'Stdio (local process)', value: 'stdio' },
                    { label: 'SSE (HTTP server)', value: 'sse' },
                  ]"
                />
              </NFormItem>

              <template v-if="mcpForm.transport === 'stdio'">
                <NFormItem label="Command" required>
                  <NInput
                    v-model:value="mcpForm.command"
                    placeholder="e.g., npx, python, node"
                  />
                </NFormItem>

                <NFormItem label="Arguments">
                  <NInput
                    v-model:value="mcpForm.args"
                    placeholder="e.g., -y @modelcontextprotocol/server-filesystem /path"
                  />
                </NFormItem>

                <NFormItem label="Environment">
                  <NInput
                    v-model:value="mcpForm.env"
                    type="textarea"
                    :rows="3"
                    placeholder="KEY=value (one per line)"
                  />
                </NFormItem>
              </template>

              <template v-else>
                <NFormItem label="URL" required>
                  <NInput
                    v-model:value="mcpForm.url"
                    placeholder="e.g., http://localhost:8000/mcp/sse"
                  />
                </NFormItem>
              </template>

              <NFormItem label="Enabled">
                <NSwitch v-model:value="mcpForm.enabled" />
              </NFormItem>
            </NForm>

            <template #footer>
              <NSpace justify="end">
                <NButton @click="showMcpModal = false">Cancel</NButton>
                <NButton type="primary" @click="saveMcpServer">
                  {{ editingMcpServer ? 'Update' : 'Add' }}
                </NButton>
              </NSpace>
            </template>
          </NModal>

          <!-- Logging Settings -->
          <NCard v-if="activeKey === 'logging'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Enable Logging">
                <NSwitch
                  v-model:value="config.logging.enabled"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Log Level">
                <NSelect
                  v-model:value="config.logging.level"
                  :options="logLevelOptions"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Max File Size (MB)">
                <NInputNumber
                  v-model:value="config.logging.max_file_size_mb"
                  :min="1"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Backup Count">
                <NInputNumber
                  v-model:value="config.logging.backup_count"
                  :min="1"
                  :max="10"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Console Output">
                <NSwitch
                  v-model:value="config.logging.console_output"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Detailed Format">
                <NSwitch
                  v-model:value="config.logging.detailed_format"
                  @update:value="markChanged"
                />
              </NFormItem>
            </NForm>
          </NCard>

          <!-- Agent tab removed (only had name field, not worth a whole tab) -->

          <!-- Footer -->
          <div class="content-footer">
            <code>{{ configPath }}</code>
          </div>
        </div>
      </NSpin>
    </NLayoutContent>
  </NLayout>
</template>

<style scoped>
.app-layout {
  height: 100vh;
  background: #000;
}

.sidebar {
  background: #000;
  border-right: 1px solid rgba(0, 240, 255, 0.18) !important;
}

.logo {
  padding: 22px 16px 18px;
  text-align: center;
  border-bottom: 1px solid rgba(255, 43, 214, 0.25);
  background: linear-gradient(180deg, rgba(255, 43, 214, 0.08), transparent);
}

.logo-icon {
  font-size: 26px;
  filter: drop-shadow(0 0 6px rgba(0, 240, 255, 0.7));
}

.logo-text {
  display: block;
  font-size: 18px;
  font-weight: 800;
  color: var(--neon-pink);
  margin-top: 8px;
  letter-spacing: 4px;
  text-shadow:
    0 0 6px rgba(255, 43, 214, 0.9),
    0 0 14px rgba(255, 43, 214, 0.5);
}

.main-content {
  padding: 28px;
  background: #000;
}

.content-wrapper {
  max-width: 900px;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.content-header h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: 1.5px;
  color: var(--neon-cyan);
  text-transform: uppercase;
  text-shadow:
    0 0 6px rgba(0, 240, 255, 0.7),
    0 0 14px rgba(0, 240, 255, 0.35);
}

.settings-card {
  margin-bottom: 16px;
  background: var(--oled-surface);
  border: 1px solid rgba(0, 240, 255, 0.18);
  box-shadow: 0 0 0 1px rgba(0, 240, 255, 0.04), 0 0 24px rgba(0, 240, 255, 0.05);
}

.empty-state {
  color: #666;
  text-align: center;
  padding: 24px;
  border: 1px dashed rgba(0, 240, 255, 0.2);
  border-radius: 4px;
}

.form-hint {
  color: #888;
  font-size: 12px;
  line-height: 1.5;
  margin: -8px 0 16px 184px;
  padding: 8px 12px;
  border-left: 2px solid rgba(255, 0, 128, 0.4);
  background: rgba(255, 0, 128, 0.04);
}

.form-hint code {
  color: #00f0ff;
  background: rgba(0, 240, 255, 0.08);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}

.form-hint strong {
  color: #b6ff00;
}

.mcp-servers {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.content-footer {
  margin-top: 28px;
  padding-top: 16px;
  border-top: 1px dashed rgba(255, 43, 214, 0.25);
}

.content-footer code {
  color: rgba(0, 240, 255, 0.55);
  font-size: 12px;
  letter-spacing: 0.5px;
}

.server-detail {
  margin-top: 8px;
  color: #777;
}

/* Models Section */
.models-section {
  max-width: 100%;
}

.models-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 24px;
  gap: 20px;
}

.models-header-text {
  flex: 1;
}

.models-description {
  margin: 0;
  color: #b0b0b0;
  font-size: 14px;
  line-height: 1.6;
}

.models-description code {
  background: var(--oled-surface-2);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 12px;
  color: var(--neon-lime);
  border: 1px solid rgba(182, 255, 26, 0.25);
}

.copilot-card {
  margin-bottom: 24px;
}

.copilot-card-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.copilot-card-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.copilot-status-text {
  color: #b0b0b0;
  font-size: 13px;
}

.copilot-status-text code {
  background: var(--oled-surface-2);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
}

.copilot-user-code {
  color: #8957e5;
  letter-spacing: 0.05em;
}

.models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 18px;
}

.model-card {
  background: var(--oled-surface) !important;
  border: 1px solid rgba(0, 240, 255, 0.2);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
  position: relative;
  overflow: hidden;
}

.model-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--neon-pink), var(--neon-cyan), transparent);
  opacity: 0.6;
}

.model-card:hover {
  border-color: var(--neon-cyan);
  transform: translateY(-2px);
  box-shadow:
    0 0 0 1px rgba(0, 240, 255, 0.3),
    0 8px 32px rgba(0, 240, 255, 0.15);
}

.model-card-default {
  border-color: var(--neon-pink) !important;
  box-shadow:
    0 0 0 1px rgba(255, 43, 214, 0.4),
    0 0 20px rgba(255, 43, 214, 0.25),
    0 0 40px rgba(255, 43, 214, 0.1);
}

.model-card-default::before {
  background: linear-gradient(90deg, var(--neon-pink), var(--neon-lime), var(--neon-cyan));
  opacity: 1;
  height: 2px;
}

.model-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.model-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.model-name {
  font-weight: 700;
  font-size: 16px;
  color: #fff;
  letter-spacing: 0.5px;
}

.default-star {
  color: var(--neon-lime);
  font-size: 18px;
  filter: drop-shadow(0 0 4px rgba(182, 255, 26, 0.8));
}

.model-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-detail-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
}

.detail-label {
  color: var(--neon-cyan);
  min-width: 84px;
  flex-shrink: 0;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  opacity: 0.8;
}

.detail-value {
  color: #ddd;
  background: var(--oled-surface-2);
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 12px;
  word-break: break-all;
  border: 1px solid rgba(255, 43, 214, 0.12);
}

.detail-url {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-models-card {
  text-align: center;
  padding: 48px 24px;
  background: var(--oled-surface) !important;
  border: 1px dashed rgba(255, 43, 214, 0.3);
}
</style>
