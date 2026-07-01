<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import HeroTerminal from './components/HeroTerminal.vue'
import DocSidebar from './components/DocSidebar.vue'
import DocArticle from './components/DocArticle.vue'
import CommandPalette from './components/CommandPalette.vue'
import { allPages, findPage } from './docs'
import { BASE, hrefFor, slugFromPath, SITE_TAGLINE } from './site'
import { applySeo } from './composables/useSeo'

const route = ref(slugFromPath(window.location.pathname))
const paletteOpen = ref(false)
const mobileNavOpen = ref(false)

const isHome = computed(() => route.value === '')
const currentPage = computed(() => findPage(route.value))

const currentIndex = computed(() =>
  currentPage.value ? allPages.findIndex((p) => p.slug === currentPage.value!.slug) : -1,
)
const prevPage = computed(() => (currentIndex.value > 0 ? allPages[currentIndex.value - 1] : null))
const nextPage = computed(() =>
  currentIndex.value >= 0 && currentIndex.value < allPages.length - 1
    ? allPages[currentIndex.value + 1]
    : null,
)

// Keep the document title and SEO meta in sync with the current route.
watch(
  [route, currentPage],
  () => {
    if (isHome.value) {
      applySeo({ slug: '', description: '' })
    } else if (currentPage.value) {
      applySeo({
        slug: currentPage.value.slug,
        title: currentPage.value.title,
        description: currentPage.value.blurb,
      })
    } else {
      applySeo({
        slug: route.value,
        title: 'Page not found',
        description: `Couldn't find that page. Clanker is ${SITE_TAGLINE}.`,
        noindex: true,
      })
    }
  },
  { immediate: true },
)

/** Client-side navigation to a slug via the History API. */
function go(slug: string) {
  const href = hrefFor(slug)
  if (href !== window.location.pathname) {
    window.history.pushState({}, '', href)
  }
  route.value = slug
  mobileNavOpen.value = false
  window.scrollTo({ top: 0, behavior: 'auto' })
}

function onPopState() {
  route.value = slugFromPath(window.location.pathname)
  mobileNavOpen.value = false
}

// Intercept clicks on internal links so they navigate without a full reload.
function onClick(e: MouseEvent) {
  if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
    return
  }
  const anchor = (e.target as HTMLElement)?.closest('a')
  if (!anchor) return
  const href = anchor.getAttribute('href')
  const target = anchor.getAttribute('target')
  if (!href || target === '_blank' || anchor.hasAttribute('download')) return
  // In-page anchors (#section) and external links pass through untouched.
  if (href.startsWith('#') || /^[a-z]+:\/\//i.test(href) || href.startsWith('mailto:')) return
  // Only handle links that live under our base path.
  if (!href.startsWith(BASE)) return

  e.preventDefault()
  go(slugFromPath(href))
}

function onKeydown(e: KeyboardEvent) {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
  } else if (e.key === '/' && !paletteOpen.value && !isTyping(e)) {
    e.preventDefault()
    paletteOpen.value = true
  }
}

function isTyping(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

onMounted(() => {
  window.addEventListener('popstate', onPopState)
  window.addEventListener('keydown', onKeydown)
  document.addEventListener('click', onClick)
})
onBeforeUnmount(() => {
  window.removeEventListener('popstate', onPopState)
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('click', onClick)
})
</script>

<template>
  <div class="shell">
    <!-- Top bar ------------------------------------------------ -->
    <header class="topbar">
      <div class="topbar__inner">
        <a class="brand" :href="hrefFor('')">
          <span class="brand__mark">
            <span class="brand__chev">❯</span><span class="brand__cur" />
          </span>
          <span class="brand__name">clanker</span>
          <span class="brand__tag">docs</span>
        </a>

        <button class="search-trigger" type="button" @click="paletteOpen = true">
          <span class="search-trigger__icon">⌕</span>
          <span class="search-trigger__label">Search docs</span>
          <span class="search-trigger__keys"><span class="kbd">⌘</span><span class="kbd">K</span></span>
        </button>

        <nav class="topbar__links">
          <a :href="hrefFor('installation')">Install</a>
          <a :href="hrefFor('usage')">Usage</a>
          <a
            class="topbar__gh"
            href="https://github.com/Nightmare99/clanker"
            target="_blank"
            rel="noopener"
            >GitHub ↗</a
          >
        </nav>

        <button
          class="topbar__burger"
          type="button"
          aria-label="Toggle navigation"
          @click="mobileNavOpen = !mobileNavOpen"
        >
          ☰
        </button>
      </div>
    </header>

    <!-- Home --------------------------------------------------- -->
    <main v-if="isHome" class="home">
      <div class="home__inner">
        <HeroTerminal />

        <section class="pillars" aria-label="What Clanker does">
          <article class="pillar">
            <span class="pillar__glyph" style="--c: var(--cyan)">[ r ]</span>
            <h3>Reads before it writes</h3>
            <p>
              Every edit starts with reading the file. Clanker explores the
              codebase, greps for patterns, and understands the why before
              touching the what.
            </p>
          </article>
          <article class="pillar">
            <span class="pillar__glyph" style="--c: var(--pink)">[ y/N ]</span>
            <h3>Asks before anything risky</h3>
            <p>
              Bash commands wait for your approval by default. System paths are
              protected, destructive commands are blocked, secrets stay out of
              the logs.
            </p>
          </article>
          <article class="pillar">
            <span class="pillar__glyph" style="--c: var(--lime)">[ +/- ]</span>
            <h3>Bring your own model</h3>
            <p>
              Anthropic, OpenAI, Azure, or Ollama. Switch models
              mid-session with <code>/model</code>. Extend it with MCP servers
              and skills.
            </p>
          </article>
        </section>

        <section class="quickstart">
          <div class="quickstart__head">
            <h2>Up and running in one line</h2>
            <p>Detects your OS and architecture, grabs the latest release.</p>
          </div>
          <div class="quickstart__term">
            <div class="quickstart__bar">
              <span class="quickstart__dots"><i /><i /><i /></span>
              <span class="quickstart__label">bash</span>
            </div>
            <pre class="quickstart__pre"><code><span class="qs-prompt">$</span> curl -fsSL https://raw.githubusercontent.com/Nightmare99/clanker/main/scripts/install.sh | bash
<span class="qs-out">✓ detected linux/amd64 · installing clanker → ~/.local/bin</span>
<span class="qs-prompt">$</span> clanker
<span class="qs-out">clanker ready. type a request, or /help for commands.</span></code></pre>
          </div>
          <div class="quickstart__cta">
            <a class="btn btn--primary" :href="hrefFor('installation')">Full install guide</a>
            <a class="btn btn--ghost" :href="hrefFor('configuration')">Configure models</a>
          </div>
        </section>
      </div>
    </main>

    <!-- Docs --------------------------------------------------- -->
    <div v-else class="docs">
      <div class="docs__inner">
        <aside class="docs__sidebar" :class="{ 'is-open': mobileNavOpen }">
          <DocSidebar :current="route" />
        </aside>

        <main class="docs__main">
          <DocArticle
            v-if="currentPage"
            :key="currentPage.slug"
            :page="currentPage"
            :index="currentIndex"
            :total="allPages.length"
          />
          <div v-else class="notfound">
            <p class="notfound__code">404</p>
            <h1>No such page</h1>
            <p>
              <code>{{ route }}.md</code> isn't part of the docs. Try the
              sidebar, or press <span class="kbd">⌘</span><span class="kbd">K</span> to search.
            </p>
            <a class="btn btn--primary" :href="hrefFor('')">Back to home</a>
          </div>

          <nav v-if="currentPage" class="pager" aria-label="Pagination">
            <a v-if="prevPage" class="pager__link pager__link--prev" :href="hrefFor(prevPage.slug)">
              <span class="pager__dir">← prev</span>
              <span class="pager__title">{{ prevPage.title }}</span>
            </a>
            <span v-else />
            <a v-if="nextPage" class="pager__link pager__link--next" :href="hrefFor(nextPage.slug)">
              <span class="pager__dir">next →</span>
              <span class="pager__title">{{ nextPage.title }}</span>
            </a>
          </nav>
        </main>
      </div>
    </div>

    <footer class="foot">
      <div class="foot__inner">
        <span class="foot__brand">❯ clanker</span>
        <span class="foot__note">A terminal-native AI coding agent · MIT licensed</span>
        <a href="https://github.com/Nightmare99/clanker" target="_blank" rel="noopener">GitHub ↗</a>
      </div>
    </footer>

    <CommandPalette :open="paletteOpen" @close="paletteOpen = false" @navigate="go" />

    <button
      v-if="mobileNavOpen"
      class="scrim"
      aria-label="Close navigation"
      @click="mobileNavOpen = false"
    />
  </div>
</template>

<style scoped>
.shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* Top bar -------------------------------------------------- */
.topbar {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(6, 7, 8, 0.78);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--line);
}
.topbar__inner {
  max-width: var(--maxw);
  margin: 0 auto;
  padding: 0 24px;
  height: 60px;
  display: flex;
  align-items: center;
  gap: 20px;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: var(--ink);
}
.brand:hover {
  text-decoration: none;
}
.brand__mark {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--pink);
}
.brand__cur {
  width: 8px;
  height: 16px;
  background: var(--lime);
  box-shadow: 0 0 8px var(--lime);
  animation: brandblink 1.2s steps(2, start) infinite;
}
@keyframes brandblink {
  to { opacity: 0.15; }
}
.brand__name {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1.1rem;
  letter-spacing: -0.01em;
}
.brand__tag {
  font-family: var(--font-mono);
  font-size: 0.66rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--cyan);
  border: 1px solid var(--line-strong);
  border-radius: 4px;
  padding: 2px 6px;
}

.search-trigger {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 240px;
  padding: 8px 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  color: var(--ink-3);
  font-family: var(--font-mono);
  font-size: 0.82rem;
  cursor: pointer;
  transition: border-color 0.14s ease, color 0.14s ease;
}
.search-trigger:hover {
  border-color: var(--line-strong);
  color: var(--ink-2);
}
.search-trigger__icon {
  color: var(--cyan);
  font-size: 1rem;
}
.search-trigger__keys {
  margin-left: auto;
  display: inline-flex;
  gap: 3px;
}

.topbar__links {
  display: inline-flex;
  align-items: center;
  gap: 20px;
  font-family: var(--font-mono);
  font-size: 0.84rem;
}
.topbar__links a {
  color: var(--ink-2);
}
.topbar__links a:hover {
  color: var(--cyan);
  text-decoration: none;
}
.topbar__gh {
  color: var(--ink-3) !important;
}

.topbar__burger {
  display: none;
  background: none;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  color: var(--ink);
  font-size: 1.1rem;
  padding: 6px 11px;
  cursor: pointer;
}

/* Home ----------------------------------------------------- */
.home__inner {
  max-width: var(--maxw);
  margin: 0 auto;
  padding: 0 24px 40px;
}

.pillars {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
  padding: 24px 0 64px;
}
.pillar {
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 26px 24px;
  background: linear-gradient(180deg, var(--surface), var(--bg-2));
  transition: border-color 0.16s ease, transform 0.16s ease;
}
.pillar:hover {
  border-color: var(--line-strong);
  transform: translateY(-3px);
}
.pillar__glyph {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 0.9rem;
  color: var(--c);
  border: 1px solid currentColor;
  border-radius: 4px;
  padding: 2px 8px;
  margin-bottom: 16px;
  opacity: 0.95;
}
.pillar h3 {
  margin: 0 0 8px;
  font-family: var(--font-mono);
  font-size: 1.02rem;
  color: var(--ink);
}
.pillar p {
  margin: 0;
  font-size: 0.92rem;
  color: var(--ink-2);
  line-height: 1.6;
}
.pillar code {
  font-family: var(--font-mono);
  font-size: 0.85em;
  color: var(--lime);
  background: var(--surface-2);
  padding: 1px 5px;
  border-radius: 4px;
}

.quickstart {
  display: grid;
  grid-template-columns: 0.8fr 1.2fr;
  gap: 40px;
  align-items: center;
  padding: 48px 36px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background:
    radial-gradient(600px 300px at 100% 0%, rgba(0, 240, 255, 0.05), transparent 60%),
    var(--bg-2);
}
.quickstart__head h2 {
  margin: 0 0 12px;
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1.7rem;
  letter-spacing: -0.01em;
  color: #fff;
}
.quickstart__head p {
  margin: 0;
  color: var(--ink-2);
}
.quickstart__term {
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-sm);
  overflow: hidden;
  background: #08090b;
}
.quickstart__bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.02);
}
.quickstart__dots {
  display: inline-flex;
  gap: 5px;
}
.quickstart__dots i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--ink-4);
}
.quickstart__label {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.quickstart__pre {
  margin: 0;
  padding: 16px 18px;
  overflow-x: auto;
  font-family: var(--font-mono);
  font-size: 0.8rem;
  line-height: 1.8;
  color: var(--ink);
}
.qs-prompt {
  color: var(--pink);
  font-weight: 700;
  margin-right: 8px;
}
.qs-out {
  color: var(--lime);
}
.quickstart__cta {
  grid-column: 1 / -1;
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

/* Docs ----------------------------------------------------- */
.docs__inner {
  max-width: var(--maxw);
  margin: 0 auto;
  padding: 0 24px;
  display: grid;
  grid-template-columns: var(--sidebar-w) minmax(0, 1fr);
  gap: 48px;
  align-items: start;
}
.docs__sidebar {
  position: sticky;
  top: 60px;
  height: calc(100vh - 60px);
  overflow-y: auto;
  padding: 32px 0 40px;
}
.docs__main {
  padding: 40px 0 80px;
  min-width: 0;
}

.notfound {
  padding: 40px 0;
}
.notfound__code {
  font-family: var(--font-display);
  font-size: 4rem;
  margin: 0;
  color: var(--pink);
}
.notfound h1 {
  font-family: var(--font-display);
  margin: 0 0 12px;
  color: #fff;
}
.notfound code {
  font-family: var(--font-mono);
  color: var(--lime);
}
.notfound .btn {
  margin-top: 18px;
}

/* Pager ---------------------------------------------------- */
.pager {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 56px;
  padding-top: 28px;
  border-top: 1px solid var(--line);
}
.pager__link {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 16px 18px;
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  color: var(--ink);
  transition: border-color 0.14s ease, background 0.14s ease;
}
.pager__link:hover {
  text-decoration: none;
  border-color: var(--line-strong);
  background: rgba(0, 240, 255, 0.03);
}
.pager__link--next {
  text-align: right;
}
.pager__dir {
  font-family: var(--font-mono);
  font-size: 0.74rem;
  letter-spacing: 0.06em;
  color: var(--ink-3);
}
.pager__title {
  font-family: var(--font-mono);
  font-size: 0.95rem;
  color: var(--cyan);
}

/* Footer --------------------------------------------------- */
.foot {
  margin-top: auto;
  border-top: 1px solid var(--line);
  background: var(--bg-2);
}
.foot__inner {
  max-width: var(--maxw);
  margin: 0 auto;
  padding: 24px;
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  font-family: var(--font-mono);
  font-size: 0.82rem;
  color: var(--ink-3);
}
.foot__brand {
  color: var(--pink);
  font-weight: 700;
}
.foot__note {
  color: var(--ink-3);
}
.foot a {
  margin-left: auto;
  color: var(--ink-2);
}

.scrim {
  display: none;
}

/* Responsive ----------------------------------------------- */
@media (max-width: 1080px) {
  .quickstart {
    grid-template-columns: 1fr;
    gap: 28px;
    padding: 32px 24px;
  }
}

@media (max-width: 860px) {
  .pillars {
    grid-template-columns: 1fr;
  }
  .search-trigger {
    min-width: 0;
    flex: 1;
  }
  .search-trigger__label {
    display: none;
  }
  .topbar__links {
    display: none;
  }
  .topbar__burger {
    display: inline-block;
  }

  .docs__inner {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
  .docs__sidebar {
    position: fixed;
    top: 60px;
    left: 0;
    z-index: 40;
    width: 282px;
    max-width: 84vw;
    height: calc(100vh - 60px);
    padding: 28px 22px;
    background: var(--surface);
    border-right: 1px solid var(--line-strong);
    transform: translateX(-105%);
    transition: transform 0.22s ease;
  }
  .docs__sidebar.is-open {
    transform: none;
  }
  .scrim {
    display: block;
    position: fixed;
    inset: 60px 0 0 0;
    z-index: 35;
    background: rgba(3, 4, 5, 0.6);
    border: none;
  }
  .pager {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 560px) {
  .foot__inner {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }
  .foot a {
    margin-left: 0;
  }
}
</style>
