<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NAlert, NButton, NCard, NInput, NPopconfirm, NSpace, NTag, useMessage } from 'naive-ui'

const props = defineProps<{ provider: 'copilot' | 'antigravity' }>()
const emit = defineEmits<{ (event: 'models-synced'): void }>()
const message = useMessage()
const google = computed(() => props.provider === 'antigravity')
const label = computed(() => google.value ? 'Google Antigravity' : 'GitHub Copilot')
const prefix = computed(() => google.value ? 'antigravity' : 'copilot')
const connected = ref(false)
const email = ref<string | null>(null)
const busy = ref(false)
const session = ref<{ id: string; url: string; code?: string; interval: number } | null>(null)
const callbackUrl = ref('')
const manual = ref(false)
const inlineError = ref('')
let timer: ReturnType<typeof setTimeout> | null = null
let generation = 0
let unmounted = false
const polling = ref(false)

async function api(path: string, body?: object) {
  const response = await fetch(`/api/${props.provider}/${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || `${label.value} request failed`)
  return data
}

async function loadStatus() {
  try {
    const data = await api('status')
    connected.value = data.connected
    email.value = data.email || null
  } catch {
    inlineError.value = 'Could not load account status. Retry the connection.'
  }
}

function stopTimer() {
  if (timer) clearTimeout(timer)
  timer = null
}

function cancelRemote(id: string) {
  return fetch(`/api/${props.provider}/login/cancel`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: id }), keepalive: true,
  }).catch(() => {})
}

async function startLogin() {
  const current = ++generation
  inlineError.value = ''
  busy.value = true
  // Open synchronously from the click, before awaiting the server, so browser
  // popup blockers don't prevent Google login. The link remains available too.
  const popup = google.value ? window.open('about:blank', '_blank') : null
  if (popup) popup.opener = null
  try {
    const data = await api('login/start', {})
    if (unmounted || current !== generation) {
      popup?.close()
      await cancelRemote(data.session_id)
      return
    }
    session.value = {
      id: data.session_id, url: data.authorization_url || data.verification_uri,
      code: data.user_code, interval: Math.max(1, data.interval || (google.value ? 1 : 5)) * 1000,
    }
    if (popup) popup.location.href = session.value.url
    schedulePoll()
  } catch (error) {
    popup?.close()
    if (current === generation) {
      inlineError.value = error instanceof Error ? error.message : 'Could not start login.'
      busy.value = false
    }
  }
}

function schedulePoll() {
  stopTimer()
  if (session.value && !unmounted) timer = setTimeout(() => pollLogin(), session.value.interval)
}

async function pollLogin(callback?: string) {
  if (!session.value) return
  if (polling.value) {
    schedulePoll()
    return
  }
  stopTimer()
  polling.value = true
  const current = generation
  const activeSession = session.value
  try {
    const data = await api('login/poll', {
      session_id: activeSession.id, ...(callback ? { callback_url: callback } : {}),
    })
    if (unmounted || current !== generation) return
    if (data.status === 'pending') {
      schedulePoll()
      return
    }
    session.value = null
    busy.value = false
    callbackUrl.value = ''
    manual.value = false
    if (data.status === 'success') {
      await loadStatus()
      message.success(`Connected! Synced ${data.models_synced} ${label.value} model(s).`)
      emit('models-synced')
    } else {
      inlineError.value = data.detail || 'Login expired. Please try again.'
    }
  } catch (error) {
    if (current !== generation) return
    await cancelRemote(activeSession.id)
    session.value = null
    busy.value = false
    callbackUrl.value = ''
    inlineError.value = error instanceof Error ? error.message : 'Login connection failed. Please retry.'
  } finally {
    polling.value = false
  }
}

function cancelLogin() {
  generation++
  stopTimer()
  if (session.value) void cancelRemote(session.value.id)
  session.value = null
  busy.value = false
  callbackUrl.value = ''
  manual.value = false
  inlineError.value = ''
}

async function refreshModels() {
  busy.value = true
  inlineError.value = ''
  try {
    const data = await api('refresh-models', {})
    message.success(`Synced ${data.models_synced} ${label.value} model(s).`)
    emit('models-synced')
  } catch (error) {
    inlineError.value = error instanceof Error ? error.message : 'Could not refresh models.'
  } finally {
    busy.value = false
  }
}

async function disconnectAccount() {
  busy.value = true
  try {
    await api('disconnect', {})
    connected.value = false
    email.value = null
    message.success('Disconnected. Your model settings are retained.')
  } catch (error) {
    inlineError.value = error instanceof Error ? error.message : 'Could not disconnect.'
  } finally {
    busy.value = false
  }
}

onMounted(loadStatus)
onUnmounted(() => {
  unmounted = true
  cancelLogin()
})
</script>

<template>
  <NCard class="account-card">
    <div class="account-heading">
      <div>
        <strong>{{ label }}</strong>
        <p v-if="session">
          <a :href="session.url" target="_blank" rel="noopener noreferrer">{{ google ? 'Open Google login' : 'Open GitHub login' }}</a>
          <template v-if="session.code"> and enter <code class="login-code">{{ session.code }}</code></template>
          <span v-else> to authorize your account.</span>
        </p>
        <p v-else-if="connected">
          {{ email || 'Account connected' }} · Models available as <code>{{ prefix }}:&lt;model&gt;</code>
        </p>
        <p v-else>Connect your {{ google ? 'Google account' : 'Copilot subscription' }} to discover available models. No separate proxy required.</p>
      </div>
      <NTag :type="session ? 'warning' : connected ? 'success' : 'default'" size="small">
        {{ session ? 'Waiting for authorization' : connected ? 'Connected' : 'Disconnected' }}
      </NTag>
    </div>
    <NAlert v-if="google" type="warning" :show-icon="false" class="account-notice">
      Unofficial integration. The <a href="https://github.com/badrisnarayanan/antigravity-claude-proxy" target="_blank" rel="noopener noreferrer">reference project</a>
      reports Google account bans associated with this use.
    </NAlert>
    <NAlert v-if="inlineError" type="error" class="account-notice">{{ inlineError }}</NAlert>
    <NSpace class="account-actions">
      <template v-if="session">
        <NButton @click="cancelLogin">Cancel</NButton>
        <NButton v-if="google" quaternary @click="manual = !manual">Use callback URL</NButton>
      </template>
      <template v-else-if="connected">
        <NButton :loading="busy" :disabled="busy" @click="refreshModels">Refresh Models</NButton>
        <NButton :disabled="busy" @click="startLogin">Reconnect</NButton>
        <NPopconfirm @positive-click="disconnectAccount">
          <template #trigger><NButton :disabled="busy" quaternary>Disconnect</NButton></template>
          Remove cached login credentials? Saved model settings will remain.
        </NPopconfirm>
      </template>
      <NButton v-else type="primary" :loading="busy" :disabled="busy" @click="startLogin">
        {{ google ? 'Sign in with Google' : 'Connect GitHub Copilot' }}
      </NButton>
    </NSpace>
    <div v-if="manual && session" class="manual-login">
      <p>On a remote machine, copy the full callback URL from the browser after approving Google access.</p>
      <NInput v-model:value="callbackUrl" type="password" placeholder="http://localhost:…/oauth-callback?code=…&state=…" autocomplete="off" />
      <NButton :disabled="!callbackUrl.trim() || polling" @click="pollLogin(callbackUrl.trim())">Complete Login</NButton>
    </div>
  </NCard>
</template>

<style scoped>
.account-card {
  background: var(--nb-surface) !important;
  border: 2px solid var(--nb-border) !important;
  box-shadow: var(--nb-shadow) !important;
  margin-bottom: 20px;
}
.account-heading { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.account-heading p, .manual-login p { font-size: 13px; margin: 8px 0 0; }
.account-actions, .account-notice, .manual-login { margin-top: 14px; }
.manual-login { display: grid; gap: 12px; }
.manual-login :deep(.n-button) { justify-self: start; }
.login-code { background: var(--nb-lime); color: #000; padding: 2px 8px; font-weight: 800; letter-spacing: .08em; }
a { color: inherit; text-decoration: underline; }
</style>
