<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { hrefFor } from '../site'

/**
 * The hero is a thesis: Clanker is a coding agent that lives in your terminal.
 * So the hero IS a terminal — it types a real prompt, then "thinks", calls
 * tools (read -> edit -> run), and streams a concluding answer with a
 * file:line reference, exactly like the CLI does. One orchestrated moment.
 */

type Line =
  | { kind: 'prompt'; text: string; typed?: boolean }
  | { kind: 'tool'; name: string; arg: string; result?: string }
  | { kind: 'stream'; text: string }
  | { kind: 'ref'; text: string }

const script: Line[] = [
  { kind: 'prompt', text: 'fix the failing auth test and run the suite', typed: true },
  { kind: 'tool', name: 'grep_search', arg: 'def test_login', result: '3 matches in tests/test_auth.py' },
  { kind: 'tool', name: 'read_file', arg: 'src/clanker/auth.py', result: 'read 84 lines' },
  { kind: 'tool', name: 'edit_file', arg: 'src/clanker/auth.py', result: 'patched null check at line 42' },
  { kind: 'tool', name: 'execute_shell', arg: 'pytest -q', result: '229 passed in 6.4s' },
  { kind: 'stream', text: 'Fixed a null dereference in the token refresh path — the session was read before the guard.' },
  { kind: 'ref', text: 'src/clanker/auth.py:42' },
]

const visible = ref<Line[]>([])
const typing = ref('')
const showCaret = ref(true)
const done = ref(false)
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

async function play() {
  for (const line of script) {
    if (line.kind === 'prompt' && line.typed) {
      await typeText(line.text)
      await wait(360)
      visible.value.push(line)
      typing.value = ''
    } else {
      visible.value.push(line)
      await wait(line.kind === 'stream' ? 520 : 420)
    }
  }
  done.value = true
}

onMounted(() => {
  reduced.value = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced.value) {
    visible.value = [...script]
    done.value = true
    showCaret.value = false
    return
  }
  // Caret blink is CSS; kick off the orchestrated sequence shortly after load.
  const id = window.setTimeout(play, 600)
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
      <p class="hero__eyebrow"><span class="hero__dot" /> AI coding agent · BYOK &amp; GitHub Copilot</p>
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

    <div class="term" role="img" aria-label="An example Clanker session: it edits a file and runs the test suite.">
      <div class="term__bar">
        <span class="term__dots"><i /><i /><i /></span>
        <span class="term__title">clanker — ~/projects/clanker</span>
        <span class="term__badge">REPL</span>
      </div>
      <div class="term__body">
        <template v-for="(line, i) in visible" :key="i">
          <div v-if="line.kind === 'prompt'" class="t-line t-prompt">
            <span class="t-caret-prompt">❯</span><span>{{ line.text }}</span>
          </div>
          <div v-else-if="line.kind === 'tool'" class="t-line t-tool">
            <span class="t-tool__name">{{ line.name }}</span>
            <span class="t-tool__arg">{{ line.arg }}</span>
            <span class="t-tool__result">✓ {{ line.result }}</span>
          </div>
          <div v-else-if="line.kind === 'stream'" class="t-line t-stream">
            {{ line.text }}
          </div>
          <div v-else-if="line.kind === 'ref'" class="t-line t-ref">
            <span class="t-ref__icon">↳</span>{{ line.text }}
          </div>
        </template>

        <div v-if="!done" class="t-line t-prompt t-prompt--live">
          <span class="t-caret-prompt">❯</span><span>{{ typing }}</span><span class="t-cursor" />
        </div>
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

/* ---- terminal ---- */
.term {
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  background: linear-gradient(180deg, #0b0d10, #07090b);
  box-shadow:
    0 0 0 1px rgba(0, 240, 255, 0.05),
    0 40px 90px -40px rgba(0, 0, 0, 0.9),
    0 0 80px -30px rgba(255, 43, 214, 0.35);
  overflow: hidden;
  min-height: 360px;
}
.term__bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 11px 16px;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--line);
}
.term__dots {
  display: inline-flex;
  gap: 7px;
}
.term__dots i {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  background: var(--ink-4);
}
.term__dots i:nth-child(1) { background: #ff5f57; }
.term__dots i:nth-child(2) { background: #febc2e; }
.term__dots i:nth-child(3) { background: #28c840; }
.term__title {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  color: var(--ink-3);
}
.term__badge {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 0.66rem;
  letter-spacing: 0.12em;
  color: var(--cyan);
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  padding: 2px 7px;
}
.term__body {
  padding: 20px 20px 26px;
  font-family: var(--font-mono);
  font-size: 0.86rem;
  line-height: 1.55;
}

.t-line {
  margin: 0 0 10px;
  animation: lineIn 0.32s ease both;
}
@keyframes lineIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}

.t-prompt {
  display: flex;
  gap: 10px;
  color: var(--ink);
}
.t-caret-prompt {
  color: var(--pink);
  font-weight: 700;
}
.t-prompt--live {
  animation: none;
}

.t-cursor {
  display: inline-block;
  width: 8px;
  height: 1.05em;
  margin-left: 2px;
  background: var(--pink);
  transform: translateY(2px);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  to { opacity: 0; }
}

.t-tool {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 10px;
  padding-left: 4px;
}
.t-tool__name {
  color: var(--cyan);
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 0.78rem;
  background: var(--cyan-dim);
}
.t-tool__arg {
  color: var(--ink-2);
}
.t-tool__result {
  color: var(--lime);
  margin-left: auto;
  font-size: 0.8rem;
}

.t-stream {
  color: var(--ink);
  border-left: 2px solid var(--pink);
  padding: 4px 0 4px 14px;
  margin-top: 14px;
  line-height: 1.6;
}

.t-ref {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--amber);
  background: rgba(255, 208, 43, 0.08);
  border: 1px solid rgba(255, 208, 43, 0.3);
  border-radius: 4px;
  padding: 4px 10px;
  font-size: 0.8rem;
}
.t-ref__icon {
  opacity: 0.7;
}

@media (max-width: 940px) {
  .hero {
    grid-template-columns: 1fr;
    gap: 36px;
    padding-top: 36px;
  }
  .term {
    min-height: 0;
  }
  .t-tool__result {
    margin-left: 0;
  }
}
</style>
