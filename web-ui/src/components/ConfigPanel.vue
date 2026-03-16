<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
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
    github_copilot: { model: string | null }
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
  GITHUB_TOKEN: boolean
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

// Available models from providers
const availableModels = ref<Record<string, string[]>>({})
const loadingModels = ref(false)

// Menu items
const menuOptions: MenuOption[] = [
  { label: 'Model', key: 'model', icon: () => h(NIcon, null, { default: () => h(HardwareChipOutline) }) },
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
  { label: 'GitHub Copilot', value: 'github_copilot' },
  { label: 'Ollama', value: 'ollama' },
]

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
const isGithubCopilotProvider = computed(() => config.value?.model.provider === 'github_copilot')

// Model options based on provider
const modelOptions = computed(() => {
  const provider = config.value?.model.provider
  if (!provider) return []

  const models = availableModels.value[provider] || []
  return models.map(m => ({ label: m, value: m }))
})

const hasAvailableModels = computed(() => modelOptions.value.length > 0)

// API functions
async function fetchConfig() {
  try {
    const response = await fetch('/api/config')
    const data = await response.json()
    config.value = data.config
    configPath.value = data.config_path
    envStatus.value = data.env_status
    // Also fetch available models
    fetchAvailableModels()
  } catch (error) {
    message.error('Failed to load configuration')
    console.error(error)
  } finally {
    loading.value = false
  }
}

async function fetchAvailableModels() {
  loadingModels.value = true
  try {
    const response = await fetch('/api/models')
    if (response.ok) {
      availableModels.value = await response.json()
    }
  } catch (error) {
    console.error('Failed to fetch models:', error)
  } finally {
    loadingModels.value = false
  }
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

onMounted(fetchConfig)
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
            <h1>{{ menuOptions.find(m => m.key === activeKey)?.label }} Settings</h1>
            <NSpace>
              <NButton
                v-if="hasChanges"
                type="primary"
                :loading="saving"
                @click="saveConfig"
              >
                Save Changes
              </NButton>
              <NButton quaternary @click="resetConfig">Reset to Defaults</NButton>
            </NSpace>
          </div>

          <NDivider />

          <!-- Model Settings -->
          <NCard v-if="activeKey === 'model'" class="settings-card">
            <NForm label-placement="left" label-width="180">
              <NFormItem label="Provider">
                <NSelect
                  v-model:value="config.model.provider"
                  :options="providerOptions"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem v-if="!isGithubCopilotProvider && !isAzureProvider && !isAzureAnthropicProvider" label="Model Name">
                <NInput
                  v-model:value="config.model.name"
                  placeholder="e.g., gpt-4o, claude-sonnet-4-20250514"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Temperature">
                <NSlider
                  v-model:value="config.model.temperature"
                  :min="0"
                  :max="2"
                  :step="0.1"
                  :format-tooltip="(v: number) => v?.toFixed(1) ?? 'Default'"
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Max Tokens">
                <NInputNumber
                  v-model:value="config.model.max_tokens"
                  :min="1"
                  :max="200000"
                  placeholder="Default"
                  clearable
                  @update:value="markChanged"
                />
              </NFormItem>

              <NFormItem label="Parallel Tool Calls">
                <NSwitch
                  v-model:value="config.model.parallel_tool_calls"
                  @update:value="markChanged"
                />
              </NFormItem>

              <template v-if="isAnthropicProvider">
                <NDivider>Extended Thinking (Anthropic)</NDivider>

                <NFormItem label="Enable Thinking">
                  <NSwitch
                    v-model:value="config.model.thinking_enabled"
                    @update:value="markChanged"
                  />
                </NFormItem>

                <NFormItem v-if="config.model.thinking_enabled" label="Thinking Budget">
                  <NInputNumber
                    v-model:value="config.model.thinking_budget_tokens"
                    :min="1000"
                    :max="100000"
                    @update:value="markChanged"
                  />
                </NFormItem>
              </template>

              <template v-if="isAzureProvider">
                <NDivider>Azure OpenAI Settings</NDivider>

                <NFormItem label="API Version">
                  <NInput
                    v-model:value="config.model.azure.api_version"
                    @update:value="markChanged"
                  />
                </NFormItem>

                <NFormItem label="Deployment Name">
                  <NSpace vertical style="width: 100%">
                    <NSelect
                      v-if="availableModels.azure?.length"
                      v-model:value="config.model.azure.deployment_name"
                      :options="availableModels.azure.map(m => ({ label: m, value: m }))"
                      filterable
                      tag
                      placeholder="Select or type deployment name"
                      @update:value="markChanged"
                    />
                    <NInput
                      v-else
                      v-model:value="config.model.azure.deployment_name"
                      placeholder="Or set via AZURE_OPENAI_DEPLOYMENT_NAME"
                      @update:value="markChanged"
                    />
                  </NSpace>
                </NFormItem>
              </template>

              <template v-if="isAzureAnthropicProvider">
                <NDivider>Azure Foundry Anthropic Settings</NDivider>

                <NFormItem label="Resource Name">
                  <NInput
                    v-model:value="config.model.azure_anthropic.resource"
                    placeholder="Or set via ANTHROPIC_FOUNDRY_RESOURCE"
                    @update:value="markChanged"
                  />
                </NFormItem>

                <NFormItem label="Deployment Name">
                  <NInput
                    v-model:value="config.model.azure_anthropic.deployment_name"
                    placeholder="Defaults to model name"
                    @update:value="markChanged"
                  />
                </NFormItem>
              </template>

              <template v-if="isGithubCopilotProvider">
                <NDivider>GitHub Copilot Settings</NDivider>

                <NAlert type="info" style="margin-bottom: 16px">
                  Authenticate with: <code>clanker login</code>
                </NAlert>

                <NFormItem label="Model">
                  <NSpace vertical style="width: 100%">
                    <NSelect
                      v-if="availableModels.github_copilot?.length"
                      v-model:value="config.model.github_copilot.model"
                      :options="availableModels.github_copilot.map(m => ({ label: m, value: m }))"
                      filterable
                      clearable
                      placeholder="Select model (or leave empty for default)"
                      :loading="loadingModels"
                      @update:value="markChanged"
                    />
                    <NInput
                      v-else
                      v-model:value="config.model.github_copilot.model"
                      placeholder="e.g., gpt-4o, claude-sonnet-4 (run 'clanker login' for model list)"
                      @update:value="markChanged"
                    />
                    <NButton size="small" @click="fetchAvailableModels" :loading="loadingModels">
                      Refresh Models
                    </NButton>
                  </NSpace>
                </NFormItem>
              </template>
            </NForm>
          </NCard>

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
</style>
