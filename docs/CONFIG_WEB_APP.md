# Clanker Web Configuration App

## Overview

A local web application for configuring Clanker settings through a user-friendly interface, launched via `clanker config` command.

---

## Command Interface

```bash
clanker config              # Start web app and open browser
clanker config --port 8765  # Use custom port
clanker config --no-browser # Start server without opening browser
```

---

## Technology Stack

### Backend

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Framework | FastAPI | Async-compatible, minimal, modern, auto OpenAPI docs |
| Server | Uvicorn | Lightweight ASGI server |

**New Python dependencies:** `fastapi`, `uvicorn`

---

### Frontend Options

#### Option A: Vue 3 + Naive UI ⭐ Recommended

| Aspect | Details |
|--------|---------|
| Framework | Vue 3 (Composition API) |
| Component Library | [Naive UI](https://www.naiveui.com/) |
| Styling | Built-in theming (excellent dark mode) |
| Build | Vite |

**Pros:**
- Naive UI has excellent form components (inputs, sliders, switches, selects)
- First-class dark mode with theme customization
- Tree-shakeable, only bundles what you use
- Clean, modern aesthetic
- Good TypeScript support

**Cons:**
- Requires Node.js for development/build

---

#### Option B: React + Shadcn/ui

| Aspect | Details |
|--------|---------|
| Framework | React 18 |
| Component Library | [Shadcn/ui](https://ui.shadcn.com/) |
| Styling | Tailwind CSS |
| Build | Vite |

**Pros:**
- Copy-paste components (no npm dependency)
- Highly customizable
- Very popular, lots of examples
- Tailwind-based theming

**Cons:**
- Larger ecosystem, more boilerplate
- Components need individual installation

---

#### Option C: Svelte + Skeleton

| Aspect | Details |
|--------|---------|
| Framework | Svelte 4 / SvelteKit |
| Component Library | [Skeleton](https://www.skeleton.dev/) |
| Styling | Tailwind CSS |
| Build | Vite |

**Pros:**
- Smallest bundle size
- No virtual DOM overhead
- Skeleton has good form components
- Simple, less boilerplate

**Cons:**
- Smaller ecosystem
- Fewer ready-made components

---

### Recommendation: **Vue 3 + Naive UI**

Best fit for a settings/config app because:
1. **Form-focused components** - Naive UI excels at forms, inputs, validation
2. **Dark mode out of the box** - Matches Clanker CLI aesthetic
3. **Balance of simplicity and power** - Less boilerplate than React, more mature than Svelte
4. **Single build output** - Can bundle into static files served by FastAPI

---

### Build & Deployment Strategy

```
clanker/
├── src/clanker/config/web/
│   ├── __init__.py
│   ├── app.py              # FastAPI app
│   ├── routes.py           # API endpoints
│   └── static/             # Built frontend assets (committed)
│       ├── index.html
│       ├── assets/
│       │   ├── index-[hash].js
│       │   └── index-[hash].css
│
└── web-ui/                  # Frontend source (for development)
    ├── package.json
    ├── vite.config.ts
    ├── src/
    │   ├── App.vue
    │   ├── main.ts
    │   └── components/
    └── dist/                # Build output → copied to static/
```

**For users:** Just `pip install clanker` - pre-built frontend included
**For contributors:** Run `npm install && npm run build` in `web-ui/` to rebuild frontend

---

## Features

### 1. Dashboard / Home
- Current configuration summary
- Quick status indicators (API keys configured, MCP servers active)
- Links to each settings section

### 2. Model Settings
- Provider selection (dropdown: anthropic, openai, azure, azure_anthropic, ollama)
- Model name input
- Temperature slider (0.0 - 2.0)
- Max tokens input
- Extended thinking toggle + budget tokens (Anthropic only)
- Provider-specific settings:
  - **Azure OpenAI:** API version, deployment name
  - **Azure Anthropic:** Resource name, deployment name

### 3. API Keys Management
- Display configured keys (masked, e.g., `sk-...abc123`)
- Environment variable indicators (show which are set via env vs config)
- Note: Keys stored in environment variables only (security)
- Link to setup instructions for each provider

### 4. Output Settings
- Syntax highlighting toggle
- Show tool calls toggle
- Stream responses toggle
- Show token usage toggle

### 5. Context Settings
- Compaction threshold slider (50-99%)
- Keep recent turns input (1-20)

### 6. Safety Settings
- Require confirmation toggle
- Sandbox commands toggle
- Max file size input
- Command timeout input

### 7. Memory Settings
- Persist sessions toggle
- Max history length input
- Storage path display (read-only)

### 8. MCP Servers
- List configured servers with status
- Add new server form:
  - Server name
  - Transport type (stdio/sse)
  - For stdio: command, args, env vars
  - For sse: URL
  - Enabled toggle
- Edit existing servers
- Delete servers
- Test connection button

### 9. Agent Settings
- Agent name input

### 10. Logging Settings
- Enabled toggle
- Log level dropdown
- Max file size input
- Backup count input
- Console output toggle
- Detailed format toggle
- View recent logs button (opens log viewer)

---

## UI/UX Requirements

### Layout
- Sidebar navigation with sections
- Main content area
- Sticky save/cancel buttons
- Responsive (works on mobile for remote access)

### Interactions
- Real-time validation
- Unsaved changes indicator
- Auto-save option or explicit save button
- Toast notifications for save success/errors
- Confirmation dialogs for destructive actions

### Theme
- Dark mode by default (matches CLI aesthetic)
- Optional light mode toggle
- Consistent with "Clanker" robot/mechanical aesthetic

---

## Technical Implementation

### Backend Endpoints

```
GET  /api/config           - Get current configuration
PUT  /api/config           - Update configuration
GET  /api/config/schema    - Get settings schema for form generation
POST /api/config/validate  - Validate config without saving
GET  /api/env-status       - Check which env vars are set
GET  /api/mcp/test/{name}  - Test MCP server connection
GET  /api/logs/recent      - Get recent log entries
POST /api/shutdown         - Gracefully shutdown config server
```

### File Structure

```
src/clanker/
├── config/
│   └── web/
│       ├── __init__.py
│       ├── app.py          # FastAPI application
│       ├── routes.py       # API endpoints
│       └── templates/
│           └── index.html  # Single-page app
```

### Security Considerations

- Bind to localhost only (127.0.0.1)
- No authentication needed (local only)
- API keys never returned in full via API
- CORS disabled (same-origin only)
- Auto-shutdown after inactivity (configurable, e.g., 30 min)

---

## Implementation Phases

### Phase 1: Core (MVP)
- [ ] Basic FastAPI server with static HTML
- [ ] Model settings page
- [ ] Output settings page
- [ ] Save/load configuration
- [ ] Browser auto-open

### Phase 2: Complete Settings
- [ ] All remaining settings sections
- [ ] MCP server management
- [ ] Validation and error handling

### Phase 3: Polish
- [ ] Dark/light theme
- [ ] Log viewer
- [ ] MCP connection testing
- [ ] Auto-shutdown on inactivity

---

## Open Questions

1. **Auto-save vs explicit save?**
   - Auto-save on change, or require clicking "Save"?

2. **Config file location display?**
   - Show path to config.yaml for manual editing?

3. **Reset to defaults?**
   - Button to reset individual sections or entire config?

4. **Import/Export?**
   - Allow downloading/uploading config.yaml?

5. **Setup wizard integration?**
   - Replace current CLI setup wizard, or keep both?

---

## Mockup

```
┌─────────────────────────────────────────────────────────────┐
│  ⚙️ CLANKER CONFIG                              [Dark 🌙]   │
├──────────────┬──────────────────────────────────────────────┤
│              │                                              │
│  📊 Dashboard│  Model Settings                              │
│  🤖 Model    │  ─────────────────────────────────────────── │
│  🔑 API Keys │                                              │
│  📤 Output   │  Provider      [Azure OpenAI     ▼]          │
│  📐 Context  │                                              │
│  🛡️ Safety   │  Model Name    [gpt-4o                    ]  │
│  💾 Memory   │                                              │
│  🔌 MCP      │  Temperature   [━━━━━━━●━━━] 0.7             │
│  🪵 Logging  │                                              │
│              │  Max Tokens    [4096                      ]  │
│              │                                              │
│              │  ☐ Extended Thinking (Anthropic only)        │
│              │                                              │
│              │                    [Save Changes]            │
│              │                                              │
└──────────────┴──────────────────────────────────────────────┘
```

---

## Acceptance Criteria

- [ ] `clanker config` starts local server and opens browser
- [ ] All settings editable through web UI
- [ ] Changes persist to config.yaml
- [ ] Server shuts down cleanly on browser close or timeout
- [ ] Works offline (no external CDN dependencies in production)
- [ ] Minimal new dependencies (<3 new packages)
