// Site-wide constants and routing helpers.
//
// Hosted as a GitHub Pages *project* site, so everything lives under the
// repo path. `import.meta.env.BASE_URL` is whatever `base` is set to in
// vite.config.ts (e.g. "/clanker/") and already has a trailing slash.

export const SITE_URL = 'https://nightmare99.github.io/clanker'
export const REPO_URL = 'https://github.com/Nightmare99/clanker'
export const SITE_NAME = 'Clanker'
export const SITE_TAGLINE = 'a terminal-native AI coding agent'

/** App base path, e.g. "/clanker/" in production or "/" in dev. */
export const BASE: string = import.meta.env.BASE_URL

/** Build an in-app href for a page slug (empty slug = home). */
export function hrefFor(slug: string): string {
  return slug ? `${BASE}${slug}` : BASE
}

/** Absolute canonical URL for a slug, used in SEO tags and the sitemap. */
export function canonicalFor(slug: string): string {
  return slug ? `${SITE_URL}/${slug}` : `${SITE_URL}/`
}

/** Read the current slug from the path, stripping the base prefix. */
export function slugFromPath(pathname: string): string {
  let p = pathname
  if (p.startsWith(BASE)) p = p.slice(BASE.length)
  return p.replace(/^\/+|\/+$/g, '')
}
