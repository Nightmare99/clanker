import MarkdownIt from 'markdown-it'
import anchor from 'markdown-it-anchor'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import shell from 'highlight.js/lib/languages/shell'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import python from 'highlight.js/lib/languages/python'
import markdownLang from 'highlight.js/lib/languages/markdown'
import powershell from 'highlight.js/lib/languages/powershell'

hljs.registerLanguage('bash', bash)
hljs.registerLanguage('sh', bash)
hljs.registerLanguage('shell', shell)
hljs.registerLanguage('console', shell)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)
hljs.registerLanguage('yml', yaml)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('markdown', markdownLang)
hljs.registerLanguage('md', markdownLang)
hljs.registerLanguage('powershell', powershell)
hljs.registerLanguage('ps1', powershell)

export interface TocEntry {
  level: number
  text: string
  slug: string
}

function slugify(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
}

const md: MarkdownIt = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: false,
  highlight(code, lang): string {
    const language = (lang || '').toLowerCase()
    let inner: string
    if (language && hljs.getLanguage(language)) {
      try {
        inner = hljs.highlight(code, { language, ignoreIllegals: true }).value
      } catch {
        inner = md.utils.escapeHtml(code)
      }
    } else {
      inner = md.utils.escapeHtml(code)
    }
    const label = language || 'text'
    // Terminal-style code block: a chrome bar carries the language label and
    // a copy affordance; the copy logic is wired up after render in the view.
    return (
      `<div class="codeblock" data-lang="${label}">` +
      `<div class="codeblock__bar">` +
      `<span class="codeblock__dots"><i></i><i></i><i></i></span>` +
      `<span class="codeblock__lang">${label}</span>` +
      `<button class="codeblock__copy" type="button" aria-label="Copy code">copy</button>` +
      `</div>` +
      `<pre class="codeblock__pre"><code class="hljs language-${label}">${inner}</code></pre>` +
      `</div>`
    )
  },
})

md.use(anchor, {
  slugify,
  permalink: anchor.permalink.linkInsideHeader({
    symbol: '#',
    placement: 'before',
    class: 'heading-anchor',
  }),
})

export interface RenderResult {
  html: string
  toc: TocEntry[]
}

export function renderMarkdown(source: string): RenderResult {
  const env: Record<string, unknown> = {}
  const tokens = md.parse(source, env)
  const toc: TocEntry[] = []

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i]
    if (t.type === 'heading_open') {
      const level = Number(t.tag.slice(1))
      // Only surface h2/h3 in the on-page contents to keep it scannable.
      if (level >= 2 && level <= 3) {
        const inline = tokens[i + 1]
        const text = inline && inline.children
          ? inline.children
              .filter((c) => c.type === 'text' || c.type === 'code_inline')
              .map((c) => c.content)
              .join('')
          : inline?.content ?? ''
        toc.push({ level, text, slug: slugify(text) })
      }
    }
  }

  return { html: md.render(source, env), toc }
}
