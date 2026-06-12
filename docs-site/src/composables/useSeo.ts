import { SITE_NAME, SITE_TAGLINE, SITE_URL, canonicalFor } from '../site'

export interface SeoInput {
  /** Page slug, '' for home. */
  slug: string
  /** Page title (without the site-name suffix). Home uses just the site name. */
  title?: string
  /** Meta description for this page. */
  description: string
  /** When true, ask crawlers not to index this URL (e.g. the not-found page). */
  noindex?: boolean
}

const DEFAULT_DESCRIPTION =
  'Clanker is a terminal-native AI coding agent. It reads files, makes surgical edits, searches your codebase, and runs commands — with safety controls and your choice of model.'

const OG_IMAGE = `${SITE_URL}/og-image.png`

function setMeta(selector: string, attr: 'name' | 'property', key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

function setLink(rel: string, href: string) {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
  if (!el) {
    el = document.createElement('link')
    el.setAttribute('rel', rel)
    document.head.appendChild(el)
  }
  el.setAttribute('href', href)
}

/**
 * Update the document title and SEO meta tags for the current page.
 * Home shows just "Clanker"; inner pages show "Title — Clanker".
 */
export function applySeo({ slug, title, description, noindex }: SeoInput): void {
  const isHome = slug === ''
  const docTitle = isHome || !title ? SITE_NAME : `${title} — ${SITE_NAME}`
  const desc = description || DEFAULT_DESCRIPTION
  const url = canonicalFor(slug)
  const ogTitle = isHome ? `${SITE_NAME} — ${SITE_TAGLINE}` : `${title} — ${SITE_NAME}`

  document.title = docTitle

  setMeta('meta[name="robots"]', 'name', 'robots', noindex ? 'noindex, follow' : 'index, follow')
  setMeta('meta[name="description"]', 'name', 'description', desc)
  setLink('canonical', url)

  setMeta('meta[property="og:title"]', 'property', 'og:title', ogTitle)
  setMeta('meta[property="og:description"]', 'property', 'og:description', desc)
  setMeta('meta[property="og:url"]', 'property', 'og:url', url)
  setMeta('meta[property="og:image"]', 'property', 'og:image', OG_IMAGE)

  setMeta('meta[name="twitter:title"]', 'name', 'twitter:title', ogTitle)
  setMeta('meta[name="twitter:description"]', 'name', 'twitter:description', desc)
  setMeta('meta[name="twitter:image"]', 'name', 'twitter:image', OG_IMAGE)
}
