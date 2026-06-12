import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Served from GitHub Pages under the repo path (https://<user>.github.io/clanker/),
// so production assets and routes need the "/clanker/" base. In dev we keep "/".
// Override with BASE_PATH if the repo is ever renamed or hosted elsewhere.
const base = process.env.BASE_PATH ?? (process.env.NODE_ENV === 'production' ? '/clanker/' : '/')

// The markdown lives in the repo's top-level docs/ directory, one level up
// from this app. Allow Vite to read it during dev and bundle it at build time.
export default defineConfig({
  base,
  plugins: [vue()],
  server: {
    fs: {
      allow: ['..'],
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
