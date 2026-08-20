<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { hrefFor } from '../site'

/**
 * The hero is a thesis: Clanker is a coding agent that lives in your
 * terminal. So the hero IS that terminal -- not a generic "code editor in a
 * browser chrome" mockup, but the actual screen Clanker boots into: the
 * block-letter CLNKR banner with its lime shimmer, the token/context gauge,
 * YOLO mode, and the bottom input bar. Every color, line of copy, and tool
 * badge here is pulled from the real TUI's own source (chat_log.py,
 * status_bar.py, styles.tcss) rather than invented, so this is what opening
 * Clanker actually looks like, not an impression of it.
 */

const CLNKR_ART =
  '  ██████╗██╗     ███╗   ██╗██╗  ██╗██████╗\n' +
  ' ██╔════╝██║     ████╗  ██║██║ ██╔╝██╔══██╗\n' +
  ' ██║     ██║     ██╔██╗ ██║█████╔╝ ██████╔╝\n' +
  ' ██║     ██║     ██║╚██╗██║██╔═██╗ ██╔══██╗\n' +
  ' ╚██████╗███████╗██║ ╚████║██║  ██╗██║  ██║\n' +
  '  ╚═════╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═╝'

const CONTEXT_REMAINING = 94
const GAUGE_WIDTH = 16
const gaugeFilled = Math.round((CONTEXT_REMAINING / 100) * GAUGE_WIDTH)
const GAUGE_BAR = '█'.repeat(gaugeFilled) + '░'.repeat(GAUGE_WIDTH - gaugeFilled)

type Line =
  | { kind: 'sys' }
  | { kind: 'model'; name: string; provider: string }
  | { kind: 'yolo' }
  | { kind: 'hint' }
  | { kind: 'rule' }
  | { kind: 'prompt'; text: string }
  | { kind: 'tool'; name: string; arg?: string; result: string }
  | { kind: 'status'; text: string }
  | { kind: 'stream'; text: string }

// The boot banner, exactly as ClankerApp renders it on first launch.
const bootLines: Line[] = [
  { kind: 'sys' },
  { kind: 'model', name: 'Claude Sonnet', provider: 'Anthropic' },
  { kind: 'yolo' },
  { kind: 'hint' },
  { kind: 'rule' },
]

// One real turn: a question about the codebase, answered by reading its own
// instructions file first -- the same read_project_instructions step every
// Clanker session opens with.
const TURN_PROMPT = 'what is this project about?'
const turnLines: Line[] = [
  { kind: 'tool', name: 'read_project_instructions', result: 'read AGENTS.md  141 lines' },
  { kind: 'tool', name: 'glob_search', arg: '**/*.py', result: '132 files matched' },
  { kind: 'status', text: 'Exploring project structure and dependencies…' },
  {
    kind: 'stream',
    text: 'Clanker is a terminal coding agent — it reads your files, edits code, and runs commands, narrating every step and asking before anything risky.',
  },
]

const visible = ref<Line[]>([])
const typing = ref('')
const reduced = ref(false)

let timers: number[] = []

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => {
    const id = window.setTimeout(resolve, ms)
    timers.push(id)
  })
}

async function typeText(text: string) {
  typing.value = ''
  for (const ch of text) {
    typing.value += ch
    await wait(34 + Math.random() * 36)
  }
}

function stepDelay(line: Line): number {
  switch (line.kind) {
    case 'rule':
      return 220
    case 'tool':
      return 480
    case 'status':
      return 520
    case 'stream':
      return 560
    default:
      return 260
  }
}

async function play() {
  for (const line of bootLines) {
    visible.value.push(line)
    await wait(stepDelay(line))
  }
  await wait(450)
  await typeText(TURN_PROMPT)
  await wait(360)
  visible.value.push({ kind: 'prompt', text: TURN_PROMPT })
  typing.value = ''
  for (const line of turnLines) {
    visible.value.push(line)
    await wait(stepDelay(line))
  }
}

onMounted(() => {
  reduced.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced.value) {
    visible.value = [...bootLines, { kind: 'prompt', text: TURN_PROMPT }, ...turnLines]
    return
  }
  const id = window.setTimeout(play, 500)
  timers.push(id)
})

onBeforeUnmount(() => {
  timers.forEach((t) => clearTimeout(t))
  timers = []
})
</script>

<template>
  <section class="hero">
    <div class="hero__intro">
      <p class="hero__eyebrow"><span class="hero__dot" /> AI coding agent · bring your own key</p>
      <h1 class="hero__title">
        Your terminal just
        <span class="hero__accent">learned to code</span>
        with you.
      </h1>
      <p class="hero__lede">
        Clanker is a command-line coding partner. It reads your files, makes
        surgical edits, searches the codebase, and runs commands — narrating
        every tool call, asking before anything risky.
      </p>
      <div class="hero__cta">
        <a class="btn btn--primary" :href="hrefFor('installation')">Install Clanker</a>
        <a class="btn btn--ghost" :href="hrefFor('usage')">Read the usage guide</a>
      </div>
      <p class="hero__hint">
        Press <span class="kbd">⌘</span><span class="kbd">K</span> anywhere to search the docs.
      </p>
    </div>

    <div
      class="term"
      role="img"
      aria-label="Clanker's terminal UI: the CLNKR boot banner in YOLO mode, then a user asking what the project is about, answered by reading AGENTS.md and searching the codebase."
    >
      <div class="term__statusbar">
        <span class="term__tokens">in:12,480&nbsp;&nbsp;out:284</span>
        <span class="term__gauge"
          ><span class="term__gauge-pct">{{ CONTEXT_REMAINING }}%</span
          ><span class="term__gauge-bar">{{ GAUGE_BAR }}</span></span
        >
      </div>

      <div class="term__body">
        <pre class="term__art" aria-hidden="true">{{ CLNKR_ART }}</pre>

        <template v-for="(line, i) in visible" :key="i">
          <div v-if="line.kind === 'sys'" class="t-line term__online">
            Systems online. Circuits humming. Ready to build.
          </div>
          <div v-else-if="line.kind === 'model'" class="t-line term__model">
            <span class="term__label">Model: </span
            ><span class="term__model-name">{{ line.name }} ({{ line.provider }})</span>
          </div>
          <div v-else-if="line.kind === 'yolo'" class="t-line term__yolo">
            <span class="term__yolo-badge">YOLO MODE</span
            ><span class="term__yolo-note"> - bash auto-approved</span>
          </div>
          <div v-else-if="line.kind === 'hint'" class="t-line term__hint">Type "/" for commands</div>
          <hr v-else-if="line.kind === 'rule'" class="t-line term__rule" />
          <div v-else-if="line.kind === 'prompt'" class="t-line t-prompt">
            <span class="t-caret-prompt">&gt;</span><span>{{ line.text }}</span>
          </div>
          <div v-else-if="line.kind === 'tool'" class="t-line t-tool">
            <div class="t-tool__header">
              <span class="t-tool__name">{{ line.name }}</span>
              <span v-if="line.arg" class="t-tool__arg">{{ line.arg }}</span>
              <span class="t-tool__check">✓</span>
            </div>
            <div class="t-tool__output">{{ line.result }}</div>
          </div>
          <div v-else-if="line.kind === 'status'" class="t-line t-status">{{ line.text }}</div>
          <div v-else-if="line.kind === 'stream'" class="t-line t-stream">{{ line.text }}</div>
        </template>
      </div>

      <div class="term__promptbar">
        <span class="term__prompt-symbol">&gt;</span>
        <span v-if="typing" class="term__prompt-typing">{{ typing }}</span>
        <span v-else class="term__prompt-placeholder">Type your message... (ctrl+c interrupt)</span>
        <span class="term__cursor" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr);
  gap: 56px;
  align-items: center;
  padding: clamp(40px, 7vw, 96px) 0 clamp(36px, 5vw, 72px);
}

.hero__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 22px;
  font-family: var(--font-mono);
  font-size: 0.74rem;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.hero__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--lime);
  box-shadow: 0 0 10px var(--lime);
}

.hero__title {
  margin: 0 0 24px;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: clamp(2.1rem, 4.6vw, 3.5rem);
  line-height: 1.06;
  letter-spacing: -0.02em;
  color: #fff;
}
.hero__accent {
  color: var(--pink);
  position: relative;
  white-space: nowrap;
}
.hero__accent::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0.06em;
  height: 0.42em;
  background: var(--pink-dim);
  z-index: -1;
}

.hero__lede {
  margin: 0 0 32px;
  max-width: 46ch;
  font-size: 1.08rem;
  color: var(--ink-2);
}

.hero__cta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 22px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 12px 22px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.88rem;
  font-weight: 700;
  letter-spacing: 0.01em;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.18s ease, background 0.18s ease;
}
.btn:hover {
  text-decoration: none;
  transform: translateY(-1px);
}
.btn--primary {
  background: var(--pink);
  color: #07060a;
  box-shadow: 0 0 0 1px var(--pink), 0 10px 30px -10px var(--pink);
}
.btn--primary:hover {
  box-shadow: 0 0 0 1px var(--pink), 0 14px 38px -10px var(--pink);
}
.btn--ghost {
  color: var(--ink);
  border: 1px solid var(--line-strong);
  background: rgba(0, 240, 255, 0.04);
}
.btn--ghost:hover {
  border-color: var(--cyan);
  background: var(--cyan-dim);
}

.hero__hint {
  margin: 0;
  font-size: 0.85rem;
  color: var(--ink-3);
}

/* ---- terminal: Clanker's actual TUI, not a generic window mockup ---- */
.term {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: #050607;
  box-shadow:
    0 0 0 1px rgba(0, 240, 255, 0.05),
    0 40px 90px -40px rgba(0, 0, 0, 0.9),
    0 0 80px -32px rgba(0, 240, 255, 0.22);
  overflow: hidden;
  min-height: 420px;
}

.term__statusbar {
  flex: none;
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 18px;
  border-bottom: 1px solid var(--line);
  font-family: var(--font-mono);
  font-size: 0.72rem;
}
.term__tokens {
  color: var(--ink-3);
  white-space: nowrap;
}
.term__gauge {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  color: var(--lime);
  white-space: nowrap;
}
.term__gauge-bar {
  letter-spacing: -1px;
}

.term__body {
  flex: 1 1 auto;
  padding: 20px 22px 8px;
  font-family: var(--font-mono);
  font-size: 0.86rem;
  line-height: 1.55;
  overflow: hidden;
}

.term__art {
  margin: 0 0 14px;
  font-size: clamp(5.5px, 1.55vw, 10.5px);
  line-height: 1.2;
  white-space: pre;
  background: linear-gradient(100deg, var(--lime) 32%, #eaffb0 48%, var(--lime) 64%);
  background-size: 220% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  text-shadow: 0 0 22px rgba(182, 255, 26, 0.22);
  animation: shimmer 6s linear infinite;
}
@media (prefers-reduced-motion: reduce) {
  .term__art {
    animation: none;
    -webkit-text-fill-color: var(--lime);
  }
}
@keyframes shimmer {
  from {
    background-position: 0% 0;
  }
  to {
    background-position: -220% 0;
  }
}

.t-line {
  margin: 0 0 10px;
  animation: lineIn 0.32s ease both;
}
@keyframes lineIn {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

.term__online {
  color: var(--lime);
  font-weight: 700;
}
.term__model,
.term__yolo,
.term__hint {
  color: var(--ink);
}
.term__label {
  color: var(--ink);
}
.term__model-name {
  color: var(--lime);
  font-weight: 700;
}
.term__yolo-badge {
  color: var(--amber);
  font-weight: 700;
}
.term__yolo-note,
.term__hint {
  color: var(--ink-3);
}
.term__rule {
  border: none;
  border-top: 3px double var(--cyan);
  opacity: 0.5;
  margin: 6px 0 16px;
}

.t-prompt {
  display: flex;
  gap: 10px;
  color: var(--ink);
  font-weight: 600;
}
.t-caret-prompt {
  color: var(--cyan);
  font-weight: 700;
}

.t-tool__header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 10px;
}
.t-tool__name {
  color: #000;
  border-radius: 3px;
  padding: 1px 8px;
  font-size: 0.78rem;
  font-weight: 700;
  background: var(--cyan);
}
.t-tool__arg {
  color: var(--ink-2);
  font-size: 0.82rem;
}
.t-tool__check {
  color: var(--lime);
  font-weight: 700;
  margin-left: auto;
}
.t-tool__output {
  border-left: 2px solid var(--cyan-dim);
  margin: 5px 0 0 2px;
  padding: 1px 0 1px 12px;
  color: rgb(150, 225, 120);
  font-size: 0.82rem;
}

.t-status {
  border-left: 2px solid var(--cyan-dim);
  margin: 5px 0 0 2px;
  padding: 1px 0 1px 12px;
  color: var(--ink-2);
  font-size: 0.82rem;
}

.t-stream {
  color: var(--ink);
  margin-top: 4px;
  line-height: 1.6;
}

.term__promptbar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 18px;
  border-top: 1px solid var(--line);
  font-family: var(--font-mono);
  font-size: 0.85rem;
}
.term__prompt-symbol {
  color: var(--cyan);
  font-weight: 700;
}
.term__prompt-placeholder {
  color: var(--ink-4);
}
.term__prompt-typing {
  color: var(--ink);
}
.term__cursor {
  display: inline-block;
  width: 7px;
  height: 1.05em;
  background: var(--cyan);
  transform: translateY(2px);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to {
    opacity: 0;
  }
}

@media (max-width: 940px) {
  .hero {
    /* minmax(0, 1fr), not 1fr -- a bare 1fr track still floors at the
       content's min-content width, and term__art (a <pre>) has real
       intrinsic width, so without the 0 floor it forces the whole page
       wider instead of letting term__body's overflow: hidden clip it. */
    grid-template-columns: minmax(0, 1fr);
    gap: 36px;
    padding-top: 36px;
  }
  .term {
    min-height: 0;
  }
}
</style>
