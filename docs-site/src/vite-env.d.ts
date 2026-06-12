/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

// Raw markdown imports (e.g. `import txt from '../../docs/x.md?raw'`)
declare module '*.md?raw' {
  const content: string
  export default content
}
