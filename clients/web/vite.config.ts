import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, searchForWorkspaceRoot } from 'vite'

export default defineConfig({
  base: '/', // nginx serves the build at https://hack.dobsinsky.dev/ (/web/... redirects there)
  plugins: [react(), tailwindcss()],
  build: {
    rolldownOptions: {
      // React Flow's react-compiler-runtime starts with "use no memo"; bundling drops the directive, harmlessly
      onLog(level, log, handler) {
        if (log.code === 'MODULE_LEVEL_DIRECTIVE' && log.message.includes('react-compiler-runtime')) return
        handler(level, log)
      },
    },
  },
  server: {
    // The code only calls relative /v1/... URLs, as in production (nginx routes /v1/ to the API).
    // Local API: `API_URL=http://localhost:8000 npm run dev`.
    proxy: {
      '/v1': { target: process.env.API_URL ?? 'https://hack.dobsinsky.dev', changeOrigin: true },
    },
    // the example specs/stories (imported with ?raw) live in the repo's examples/
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), '../../examples'] },
  },
})
