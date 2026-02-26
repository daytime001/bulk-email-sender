import path from 'path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
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
