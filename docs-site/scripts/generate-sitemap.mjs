// Generates public/sitemap.xml from the page slugs declared in src/docs.ts,
// so the sitemap can never drift from the actual routes. Runs via the
// "presitemap"/build npm scripts before vite build.
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SITE_URL = 'https://nightmare99.github.io/clanker'

const docsSrc = readFileSync(resolve(__dirname, '../src/docs.ts'), 'utf8')
const slugs = [...docsSrc.matchAll(/slug:\s*'([^']+)'/g)].map((m) => m[1])

const today = new Date().toISOString().slice(0, 10)

const urls = [
  { loc: `${SITE_URL}/`, priority: '1.0', freq: 'weekly' },
  ...slugs.map((slug) => ({
    loc: `${SITE_URL}/${slug}`,
    priority: '0.8',
    freq: 'monthly',
  })),
]

const xml =
  '<?xml version="1.0" encoding="UTF-8"?>\n' +
  '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
  urls
    .map(
      (u) =>
        `  <url>\n    <loc>${u.loc}</loc>\n    <lastmod>${today}</lastmod>\n` +
        `    <changefreq>${u.freq}</changefreq>\n    <priority>${u.priority}</priority>\n  </url>`,
    )
    .join('\n') +
  '\n</urlset>\n'

writeFileSync(resolve(__dirname, '../public/sitemap.xml'), xml)
console.log(`sitemap.xml written with ${urls.length} URLs`)
