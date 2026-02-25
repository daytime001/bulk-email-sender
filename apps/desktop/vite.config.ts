import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
  },
  build: {
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return
          }
          if (id.includes('react') || id.includes('scheduler')) {
            return 'react-vendor'
          }
          if (id.includes('antd') || id.includes('@ant-design') || id.includes('rc-')) {
            return 'antd-vendor'
          }
          if (id.includes('@tauri-apps')) {
            return 'tauri-vendor'
          }
          return 'vendor'
        },
      },
    },
  },
})
