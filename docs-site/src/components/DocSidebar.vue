<script setup lang="ts">
import { docGroups } from '../docs'
import { hrefFor } from '../site'

// Navigation happens through the global link interceptor in App.vue, so the
// sidebar only needs to know which page is active to highlight it.
defineProps<{ current: string }>()
</script>

<template>
  <nav class="tree" aria-label="Documentation">
    <div class="tree__root">
      <span class="tree__root-icon">▸</span>
      <span class="tree__root-name">docs</span>
      <span class="tree__root-count">{{ docGroups.reduce((n, g) => n + g.pages.length, 0) }} files</span>
    </div>

    <div v-for="group in docGroups" :key="group.label" class="tree__group">
      <p class="tree__label">
        <span class="tree__sigil">{{ group.sigil }}</span>{{ group.label }}
      </p>
      <ul class="tree__list">
        <li v-for="page in group.pages" :key="page.slug">
          <a
            class="tree__item"
            :class="{ 'is-active': page.slug === current }"
            :href="hrefFor(page.slug)"
          >
            <span class="tree__pipe" aria-hidden="true">└─</span>
            <span class="tree__name">{{ page.slug }}.md</span>
          </a>
        </li>
      </ul>
    </div>
  </nav>
</template>

<style scoped>
.tree {
  font-family: var(--font-mono);
  font-size: 0.84rem;
}
.tree__root {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 4px 14px;
  color: var(--ink-2);
  border-bottom: 1px solid var(--line);
  margin-bottom: 16px;
}
.tree__root-icon {
  color: var(--cyan);
}
.tree__root-name {
  color: var(--cyan);
  font-weight: 700;
}
.tree__root-count {
  margin-left: auto;
  font-size: 0.7rem;
  color: var(--ink-4);
}

.tree__group {
  margin-bottom: 22px;
}
.tree__label {
  margin: 0 0 8px;
  font-size: 0.68rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink-3);
}
.tree__sigil {
  color: var(--ink-4);
  margin-right: 7px;
}

.tree__list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.tree__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  color: var(--ink-2);
  border-left: 2px solid transparent;
  transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
}
.tree__item:hover {
  background: rgba(255, 255, 255, 0.03);
  color: var(--ink);
  text-decoration: none;
}
.tree__pipe {
  color: var(--ink-4);
}
.tree__item.is-active {
  background: var(--pink-dim);
  color: var(--pink);
  border-left-color: var(--pink);
}
.tree__item.is-active .tree__pipe {
  color: var(--pink);
}
.tree__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
