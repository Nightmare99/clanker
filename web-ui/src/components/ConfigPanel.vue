<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
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
  SettingsOutline,
  KeyOutline,
  CodeSlashOutline,
  ShieldCheckmarkOutline,
  ServerOutline,
  DocumentTextOutline,
  ExtensionPuzzleOutline,
  HardwareChipOutline,
  ColorPaletteOutline,
  AddOutline,
  CreateOutline,
  TrashOutline,
  CheckmarkCircleOutline,
  PlayOutline,
  StarOutline,
  Star,
} from '@vicons/ionicons5'
import { h } from 'vue'

// Types
interface Config {
  agent: { name: string }
  model: {
    provider: string
    name: string
    temperature: number | null
    max_tokens: number | null
    thinking_enabled: boolean
    thinking_budget_tokens: number
    parallel_tool_calls: boolean
    azure: { api_version: string; deployment_name: string | null }
    azure_anthropic: { resource: string | null; deployment_name: string | null }
  }
  safety: {
    require_confirmation: boolean
    sandbox_commands: boolean
    max_file_size: number
    command_timeout: number
  }
  output: {
    syntax_highlighting: boolean
    show_tool_calls: boolean
    stream_responses: boolean
    show_token_usage: boolean
  }
  context: {
    compaction_threshold: number
    keep_recent_turns: number
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

interface EnvStatus {
  OPENAI_API_KEY: boolean
  ANTHROPIC_API_KEY: boolean
  AZURE_OPENAI_API_KEY: boolean
  AZURE_OPENAI_ENDPOINT: boolean
  AZURE_OPENAI_DEPLOYMENT_NAME: boolean
  ANTHROPIC_FOUNDRY_API_KEY: boolean
  ANTHROPIC_FOUNDRY_RESOURCE: boolean
}

interface ModelConfig {
  name: string
  provider: string
  api_key: string | null
  base_url: string | null
  model: string | null
  deployment_name: string | null
  api_version: string | null
}

// State
const message = useMessage()
const loading = ref(true)
const saving = ref(false)
const activeKey = ref('model')
const config = ref<Config | null>(null)
const configPath = ref('')
const envStatus = ref<EnvStatus | null>(null)
const hasChanges = ref(false)

// Models management
const models = ref<ModelConfig[]>([])
const defaultModel = ref<string | null>(null)
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
  { label: 'API Keys', key: 'keys', icon: () => h(NIcon, null, { default: () => h(KeyOutline) }) },
  { label: 'Output', key: 'output', icon: () => h(NIcon, null, { default: () => h(CodeSlashOutline) }) },
  { label: 'Context', key: 'context', icon: () => h(NIcon, null, { default: () => h(ColorPaletteOutline) }) },
  { label: 'Safety', key: 'safety', icon: () => h(NIcon, null, { default: () => h(ShieldCheckmarkOutline) }) },
  { label: 'Memory', key: 'memory', icon: () => h(NIcon, null, { default: () => h(ServerOutline) }) },
  { label: 'MCP Servers', key: 'mcp', icon: () => h(NIcon, null, { default: () => h(ExtensionPuzzleOutline) }) },
  { label: 'Logging', key: 'logging', icon: () => h(NIcon, null, { default: () => h(DocumentTextOutline) }) },
  { label: 'Agent', key: 'agent', icon: () => h(NIcon, null, { default: () => h(SettingsOutline) }) },
]

const providerOptions = [
  { label: 'Azure OpenAI', value: 'azure' },
  { label: 'OpenAI', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
  { label: 'Azure Anthropic (Foundry)', value: 'azure_anthropic' },
  { label: 'Ollama', value: 'ollama' },
]

// Provider options for the new JSON-based model config
const modelProviderOptions = [
  { label: 'OpenAI', value: 'OpenAI', description: 'GPT-4, GPT-4o, etc.' },
  { label: 'Azure OpenAI', value: 'AzureOpenAI', description: 'OpenAI models on Azure' },
  { label: 'Anthropic', value: 'Anthropic', description: 'Claude models' },
  { label: 'Ollama', value: 'Ollama', description: 'Local models via Ollama' },
]

// Provider colors and icons for visual distinction
const providerStyles: Record<string, { color: string; bgColor: string }> = {
  'OpenAI': { color: '#10a37f', bgColor: 'rgba(16, 163, 127, 0.1)' },
  'AzureOpenAI': { color: '#0078d4', bgColor: 'rgba(0, 120, 212, 0.1)' },
  'Anthropic': { color: '#d97706', bgColor: 'rgba(217, 119, 6, 0.1)' },
  'Ollama': { color: '#6366f1', bgColor: 'rgba(99, 102, 241, 0.1)' },
}

const logLevelOptions = [
  { label: 'DEBUG', value: 'DEBUG' },
  { label: 'INFO', value: 'INFO' },
  { label: 'WARNING', value: 'WARNING' },
  { label: 'ERROR', value: 'ERROR' },
  { label: 'CRITICAL', value: 'CRITICAL' },
]

// Computed
const isAnthropicProvider = computed(() =>
  config.value?.model.provider === 'anthropic' || config.value?.model.provider === 'azure_anthropic'
)

const isAzureProvider = computed(() => config.value?.model.provider === 'azure')
const isAzureAnthropicProvider = computed(() => config.value?.model.provider === 'azure_anthropic')

// Model form computed
const isModelFormAzure = computed(() => modelForm.value.provider === 'AzureOpenAI')
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
    envStatus.value = data.env_status
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

          <!-- API Keys -->
          <NCard v-if="activeKey === 'keys'" class="settings-card">
            <NAlert type="info" style="margin-bottom: 16px">
              API keys are read from environment variables for security.
              Set them in your shell profile or .env file.
            </NAlert>

            <div class="env-status-grid">
              <div v-for="(isSet, key) in envStatus" :key="key" class="env-item">
                <NTag :type="isSet ? 'success' : 'default'" size="small">
                  {{ isSet ? '✓' : '○' }}
                </NTag>
                <code>{{ key }}</code>
              </div>
            </div>
          </NCard>

          <!-- Output Settings -->
          <NCard v-if="activeKey === 'output'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Syntax Highlighting">
                <NSwitch
                  v-model:value="config.output.syntax_highlighting"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Show Tool Calls">
                <NSwitch
                  v-model:value="config.output.show_tool_calls"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Stream Responses">
                <NSwitch
                  v-model:value="config.output.stream_responses"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Show Token Usage">
                <NSwitch
                  v-model:value="config.output.show_token_usage"
                  @update:value="markChanged"
                />
              </NFormItem>
            </NForm>
          </NCard>

          <!-- Context Settings -->
          <NCard v-if="activeKey === 'context'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Compaction Threshold">
                <NSlider
                  v-model:value="config.context.compaction_threshold"
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
            </NForm>
          </NCard>

          <!-- Safety Settings -->
          <NCard v-if="activeKey === 'safety'" class="settings-card">
            <NForm label-placement="left" label-width="180">
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
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Command Timeout (ms)">
                <NInputNumber
                  v-model:value="config.safety.command_timeout"
                  :min="1000"
                  @update:value="markChanged"
                />
              </NFormItem>
            </NForm>
          </NCard>

          <!-- Memory Settings -->
          <NCard v-if="activeKey === 'memory'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Persist Sessions">
                <NSwitch
                  v-model:value="config.memory.persist_sessions"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Max History Length">
                <NInputNumber
                  v-model:value="config.memory.max_history_length"
                  :min="1"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Storage Path">
                <NInput
                  :value="config.memory.storage_path"
                  disabled
                  placeholder="Read-only"
                />
              </NFormItem>
            </NForm>
          </NCard>

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

          <!-- Agent Settings -->
          <NCard v-if="activeKey === 'agent'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Agent Name">
                <NInput
                  v-model:value="config.agent.name"
                  placeholder="Clanker"
                  @update:value="markChanged"
                />
              </NFormItem>
            </NForm>
          </NCard>

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
}

.sidebar {
  background: #141414;
}

.logo {
  padding: 20px;
  text-align: center;
  border-bottom: 1px solid #333;
}

.logo-icon {
  font-size: 24px;
}

.logo-text {
  display: block;
  font-size: 18px;
  font-weight: bold;
  color: #63e2b7;
  margin-top: 8px;
  letter-spacing: 2px;
}

.main-content {
  padding: 24px;
  background: #1a1a1a;
}

.content-wrapper {
  max-width: 800px;
}

.content-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.content-header h1 {
  margin: 0;
  font-size: 24px;
  color: #fff;
}

.settings-card {
  margin-bottom: 16px;
}

.env-status-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}

.env-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.env-item code {
  font-size: 13px;
  color: #aaa;
}

.empty-state {
  color: #666;
  text-align: center;
  padding: 20px;
}

.mcp-servers {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.content-footer {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid #333;
}

.content-footer code {
  color: #666;
  font-size: 12px;
}

.server-detail {
  margin-top: 8px;
  color: #666;
}

/* Models Section Styles */
.models-section {
  max-width: 100%;
}

.models-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.models-header-text {
  flex: 1;
}

.models-description {
  margin: 0;
  color: #888;
  font-size: 14px;
}

.models-description code {
  background: #2a2a2a;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}

.models-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.model-card {
  border: 1px solid #333;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.model-card:hover {
  border-color: #555;
}

.model-card-default {
  border-width: 2px;
  box-shadow: 0 0 12px rgba(99, 226, 183, 0.15);
}

.model-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.model-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.model-name {
  font-weight: 600;
  font-size: 16px;
}

.default-star {
  color: #f0c000;
  font-size: 16px;
}

.model-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.model-detail-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
}

.detail-label {
  color: #888;
  min-width: 80px;
  flex-shrink: 0;
}

.detail-value {
  color: #aaa;
  background: #2a2a2a;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  word-break: break-all;
}

.detail-url {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-models-card {
  text-align: center;
  padding: 40px 20px;
}
</style>
