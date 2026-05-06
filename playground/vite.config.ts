import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Built-in scenarios are imported with `?raw` from
    // `../examples/scenarios/*.yaml` and `../examples/agent-cards/*.json`
    // so the playground stays in lockstep with whatever the CLI runs.
    // Vite's dev server otherwise restricts imports to its project root.
    fs: { allow: ['..'] },
  },
})
