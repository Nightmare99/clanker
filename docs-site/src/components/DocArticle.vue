<script setup lang="ts">
import { computed, ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { renderMarkdown } from '../composables/useMarkdown'
import type { DocPage } from '../docs'

const props = defineProps<{ page: DocPage; index: number; total: number }>()

const articleEl = ref<HTMLElement | null>(null)
const activeSlug = ref('')

const rendered = computed(() => renderMarkdown(props.page.body))

let observer: IntersectionObserver | null = null

function wireCopyButtons() {
  const buttons = articleEl.value?.querySelectorAll<HTMLButtonElement>('.codeblock__copy')
  buttons?.forEach((btn) => {
    btn.onclick = () => {
      const code = btn.closest('.codeblock')?.querySelector('code')?.textContent ?? ''
      navigator.clipboard?.writeText(code).then(() => {
        btn.textContent = 'copied'
        btn.classList.add('is-copied')
        window.setTimeout(() => {
          btn.textContent = 'copy'
          btn.classList.remove('is-copied')
        }, 1400)
      })
    }
  })
}

function observeHeadings() {
  observer?.disconnect()
  const headings = articleEl.value?.querySelectorAll<HTMLElement>('h2[id], h3[id]')
  if (!headings || headings.length === 0) return
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) activeSlug.value = entry.target.id
      }
    },
    { rootMargin: '-90px 0px -70% 0px', threshold: 0 },
  )
  headings.forEach((h) => observer!.observe(h))
}

async function refresh() {
  await nextTick()
  wireCopyButtons()
  observeHeadings()
}

watch(() => props.page.slug, refresh)
onMounted(refresh)
onBeforeUnmount(() => observer?.disconnect())

const num = computed(() => String(props.index + 1).padStart(2, '0'))
</script>

<template>
  <article class="doc">
    <header class="doc__head">
      <nav class="doc__crumbs" aria-label="Breadcrumb">
        <span class="doc__sigil">❯</span>
        <span>clanker</span>
        <span class="doc__sep">/</span>
        <span>docs</span>
        <span class="doc__sep">/</span>
        <span class="doc__crumb-active">{{ page.slug }}.md</span>
      </nav>
      <span class="doc__counter">{{ num }} / {{ String(total).padStart(2, '0') }}</span>
    </header>

    <div class="doc__layout">
      <div ref="articleEl" class="doc__body markdown" v-html="rendered.html" />

      <aside v-if="rendered.toc.length > 1" class="doc__toc" aria-label="On this page">
        <p class="doc__toc-title">On this page</p>
        <ul>
          <li
            v-for="entry in rendered.toc"
            :key="entry.slug"
            :class="['doc__toc-item', `lvl-${entry.level}`, { 'is-active': entry.slug === activeSlug }]"
          >
            <a :href="`#${entry.slug}`">{{ entry.text }}</a>
          </li>
        </ul>
      </aside>
    </div>
  </article>
</template>

<style scoped>
.doc__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  margin-bottom: 28px;
  border-bottom: 1px solid var(--line);
}
.doc__crumbs {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  color: var(--ink-3);
}
.doc__sigil {
  color: var(--pink);
}
.doc__sep {
  color: var(--ink-4);
}
.doc__crumb-active {
  color: var(--cyan);
}
.doc__counter {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  color: var(--ink-4);
  letter-spacing: 0.1em;
}

.doc__layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--toc-w);
  gap: 48px;
  align-items: start;
}

.doc__toc {
  position: sticky;
  top: 96px;
  font-family: var(--font-mono);
}
.doc__toc-title {
  margin: 0 0 12px;
  font-size: 0.68rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.doc__toc ul {
  list-style: none;
  margin: 0;
  padding: 0;
  border-left: 1px solid var(--line);
}
.doc__toc-item a {
  display: block;
  padding: 5px 0 5px 14px;
  margin-left: -1px;
  border-left: 2px solid transparent;
  color: var(--ink-3);
  font-size: 0.8rem;
  line-height: 1.4;
}
.doc__toc-item.lvl-3 a {
  padding-left: 26px;
  font-size: 0.76rem;
}
.doc__toc-item a:hover {
  color: var(--ink);
  text-decoration: none;
}
.doc__toc-item.is-active a {
  color: var(--cyan);
  border-left-color: var(--cyan);
}

@media (max-width: 1080px) {
  .doc__layout {
    grid-template-columns: minmax(0, 1fr);
  }
  .doc__toc {
    display: none;
  }
}
</style>
