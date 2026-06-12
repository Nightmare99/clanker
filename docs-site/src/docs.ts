// Central registry of documentation pages.
//
// Each page imports the real markdown straight from the repo's top-level
// `docs/` directory, so the site never drifts from the source of truth.
// Pages are grouped by the order someone actually learns the tool in:
// get it running, learn what it can do, then operate it day to day.

import installation from '../../docs/installation.md?raw'
import usage from '../../docs/usage.md?raw'
import configuration from '../../docs/configuration.md?raw'
import copilot from '../../docs/copilot.md?raw'
import tools from '../../docs/tools.md?raw'
import skills from '../../docs/skills.md?raw'
import workflows from '../../docs/workflows.md?raw'
import mcp from '../../docs/mcp.md?raw'
import logging from '../../docs/logging.md?raw'
import development from '../../docs/development.md?raw'
import troubleshooting from '../../docs/troubleshooting.md?raw'

export interface DocPage {
  /** URL slug, used in the hash route (#/usage). */
  slug: string
  /** Sidebar label. */
  title: string
  /** One-line description for search results and the command palette. */
  blurb: string
  /** Raw markdown content. */
  body: string
}

export interface DocGroup {
  /** Group heading shown in the sidebar. */
  label: string
  /** A terminal-flavoured prefix shown before the group name. */
  sigil: string
  pages: DocPage[]
}

export const docGroups: DocGroup[] = [
  {
    label: 'Getting started',
    sigil: '~/',
    pages: [
      {
        slug: 'installation',
        title: 'Installation',
        blurb: 'One-line install, pre-built binaries, pip, and building from source.',
        body: installation,
      },
      {
        slug: 'usage',
        title: 'Usage',
        blurb: 'Modes, CLI flags, interactive commands, and command approval.',
        body: usage,
      },
      {
        slug: 'configuration',
        title: 'Configuration',
        blurb: 'Models, config file, environment variables, and the web UI.',
        body: configuration,
      },
      {
        slug: 'copilot',
        title: 'Copilot mode',
        blurb: 'Use GitHub Copilot with native SDK session management.',
        body: copilot,
      },
    ],
  },
  {
    label: 'Capabilities',
    sigil: '::',
    pages: [
      {
        slug: 'tools',
        title: 'Tools',
        blurb: 'The built-in tools the agent reaches for: read, edit, search, run.',
        body: tools,
      },
      {
        slug: 'skills',
        title: 'Skills',
        blurb: 'Capabilities the agent discovers and loads on its own.',
        body: skills,
      },
      {
        slug: 'workflows',
        title: 'Workflows',
        blurb: 'Canned prompts you fire deliberately with /workflow.',
        body: workflows,
      },
      {
        slug: 'mcp',
        title: 'MCP servers',
        blurb: 'Extend the agent with Model Context Protocol servers.',
        body: mcp,
      },
    ],
  },
  {
    label: 'Operations',
    sigil: '$ ',
    pages: [
      {
        slug: 'logging',
        title: 'Logging',
        blurb: 'Log files, rotation, levels, and what gets recorded.',
        body: logging,
      },
      {
        slug: 'development',
        title: 'Development',
        blurb: 'Local setup, tests, code quality, and architecture.',
        body: development,
      },
      {
        slug: 'troubleshooting',
        title: 'Troubleshooting',
        blurb: 'Fixes for provider, MCP, Copilot, and general issues.',
        body: troubleshooting,
      },
    ],
  },
]

// Flat list for routing and search.
export const allPages: DocPage[] = docGroups.flatMap((g) => g.pages)

export function findPage(slug: string): DocPage | undefined {
  return allPages.find((p) => p.slug === slug)
}

export const defaultSlug = 'installation'
