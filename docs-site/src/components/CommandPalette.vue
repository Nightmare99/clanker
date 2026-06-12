<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { allPages } from '../docs'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'navigate', slug: string): void }>()

const query = ref('')
const active = ref(0)
const inputEl = ref<HTMLInputElement | null>(null)

const results = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return allPages
  return allPages.filter(
    (p) =>
      p.title.toLowerCase().includes(q) ||
      p.blurb.toLowerCase().includes(q) ||
      p.slug.includes(q),
  )
})

watch(
  () => props.open,
  async (isOpen) => {
    if (isOpen) {
      query.value = ''
      active.value = 0
      await nextTick()
      inputEl.value?.focus()
    }
  },
)

watch(results, () => {
  active.value = 0
})

function move(delta: number) {
  if (results.value.length === 0) return
  active.value = (active.value + delta + results.value.length) % results.value.length
}

function choose(slug?: string) {
  const target = slug ?? results.value[active.value]?.slug
  if (target) {
    emit('navigate', target)
    emit('close')
  }
}
</script>

<template>
  <Transition name="palette">
    <div v-if="open" class="palette" @click.self="emit('close')">
      <div class="palette__box" role="dialog" aria-modal="true" aria-label="Search documentation">
        <div class="palette__search">
          <span class="palette__sigil">❯</span>
          <input
            ref="inputEl"
            v-model="query"
            class="palette__input"
            type="text"
            placeholder="Search the docs…"
            spellcheck="false"
            autocomplete="off"
            @keydown.down.prevent="move(1)"
            @keydown.up.prevent="move(-1)"
            @keydown.enter.prevent="choose()"
            @keydown.esc.prevent="emit('close')"
          />
          <span class="kbd">esc</span>
        </div>
        <ul class="palette__results">
          <li
            v-for="(p, i) in results"
            :key="p.slug"
            class="palette__item"
            :class="{ 'is-active': i === active }"
            @mouseenter="active = i"
            @click="choose(p.slug)"
          >
            <span class="palette__item-title">{{ p.title }}</span>
            <span class="palette__item-blurb">{{ p.blurb }}</span>
          </li>
          <li v-if="results.length === 0" class="palette__empty">
            No pages match "{{ query }}". Try a tool, command, or topic.
          </li>
        </ul>
        <div class="palette__footer">
          <span><span class="kbd">↑</span><span class="kbd">↓</span> to navigate</span>
          <span><span class="kbd">↵</span> to open</span>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.palette {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(3, 4, 5, 0.74);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 14vh 20px 20px;
}
.palette__box {
  width: min(620px, 100%);
  background: var(--surface);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  box-shadow: 0 40px 90px -30px rgba(0, 0, 0, 0.9), 0 0 60px -25px var(--pink);
  overflow: hidden;
}
.palette__search {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--line);
}
.palette__sigil {
  font-family: var(--font-mono);
  color: var(--pink);
  font-weight: 700;
}
.palette__input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 1rem;
}
.palette__input::placeholder {
  color: var(--ink-4);
}
.palette__results {
  list-style: none;
  margin: 0;
  padding: 8px;
  max-height: 50vh;
  overflow-y: auto;
}
.palette__item {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 11px 13px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  border: 1px solid transparent;
}
.palette__item.is-active {
  background: var(--pink-dim);
  border-color: rgba(255, 43, 214, 0.35);
}
.palette__item-title {
  font-family: var(--font-mono);
  font-size: 0.92rem;
  color: var(--ink);
}
.palette__item.is-active .palette__item-title {
  color: var(--pink);
}
.palette__item-blurb {
  font-size: 0.82rem;
  color: var(--ink-3);
}
.palette__empty {
  padding: 18px 13px;
  color: var(--ink-3);
  font-size: 0.88rem;
}
.palette__footer {
  display: flex;
  gap: 18px;
  padding: 12px 18px;
  border-top: 1px solid var(--line);
  font-size: 0.78rem;
  color: var(--ink-3);
}
.palette__footer .kbd {
  margin-right: 3px;
}

.palette-enter-active,
.palette-leave-active {
  transition: opacity 0.16s ease;
}
.palette-enter-from,
.palette-leave-to {
  opacity: 0;
}
.palette-enter-active .palette__box {
  transition: transform 0.18s ease;
}
.palette-enter-from .palette__box {
  transform: translateY(-8px) scale(0.99);
}
</style>
