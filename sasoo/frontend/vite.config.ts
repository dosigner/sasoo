import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

const BACKEND_PORT = 8000;
const BACKEND_TARGET = `http://localhost:${BACKEND_PORT}`;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false,
      },
      '/static': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false,
      },
      '/health': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        secure: false,
      },
      '/ws': {
        target: `ws://localhost:${BACKEND_PORT}`,
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          pdf: ['pdfjs-dist'],
          markdown: ['react-markdown', 'remark-gfm', 'rehype-highlight'],
        },
      },
    },
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'lucide-react'],
  },
  base: './',
});
