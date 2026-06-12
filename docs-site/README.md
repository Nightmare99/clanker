# Clanker docs site

A Vue 3 + Vite documentation site for Clanker. It renders the markdown in the
repo's top-level [`docs/`](../docs) directory directly, so the site never drifts
from the source of truth — edit a `.md` file and the page updates.

## Develop

```bash
cd docs-site
npm install
npm run dev      # http://localhost:5173
```

## Build

```bash
npm run build    # generates sitemap.xml, type-checks, then outputs static files to docs-site/dist/
npm run preview  # serve the production build locally
```

The site uses the History API for clean URLs (e.g. `/clanker/usage`). The base
path is computed in `vite.config.ts`: `/clanker/` in production, `/` in dev, and
overridable via the `BASE_PATH` env var. To build exactly as GitHub Pages serves
it:

```bash
NODE_ENV=production BASE_PATH=/clanker/ npm run build
NODE_ENV=production BASE_PATH=/clanker/ npm run preview   # http://localhost:4173/clanker/
```

## Deploy

Pushes to `main` that touch `docs-site/`, `docs/`, or the workflow trigger
[`.github/workflows/deploy-docs.yml`](../.github/workflows/deploy-docs.yml),
which builds with `BASE_PATH=/clanker/` and publishes `dist/` to GitHub Pages at
<https://nightmare99.github.io/clanker/>. Deep links survive refreshes via the
SPA fallback (`public/404.html` encodes the path, `index.html` decodes it).

## SEO

- Per-page `<title>`, description, canonical, Open Graph, and Twitter card tags
  are applied client-side by `src/composables/useSeo.ts` on every navigation.
- The not-found view sends `robots: noindex, follow`; everything else is indexable.
- `public/robots.txt` points crawlers at `sitemap.xml`, which is regenerated from
  `src/docs.ts` on every build by `scripts/generate-sitemap.mjs`.
- `public/og-image.png` (1200×630) is the social share card; regenerate it with
  `rsvg-convert -w 1200 -h 630 scripts/og-image.svg -o public/og-image.png`.

## How it's wired

| File | Role |
|------|------|
| `src/docs.ts` | Imports each `../docs/*.md` and groups pages for the sidebar. |
| `src/composables/useMarkdown.ts` | Renders markdown, highlights code, builds the on-page table of contents. |
| `src/components/HeroTerminal.vue` | The self-typing REPL session on the home page. |
| `src/components/DocSidebar.vue` | File-tree navigation mirroring `docs/`. |
| `src/components/DocArticle.vue` | Renders a page, its breadcrumb, TOC, and copy buttons. |
| `src/components/CommandPalette.vue` | `⌘K` / `/` search across all pages. |
| `src/styles/` | Design tokens (`main.css`) and prose styles (`markdown.css`). |

## Adding a page

1. Add the markdown file to `../docs/`.
2. Import it in `src/docs.ts` and add an entry to the relevant group.

That's it — routing, search, sidebar, and prev/next links update automatically.
