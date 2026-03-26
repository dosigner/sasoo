import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

const BACKEND_PORT = 8000;
const BACKEND_TARGET = `http://localhost:${BACKEND_PORT}`;

function patchPdfViewerCss() {
  return {
    name: 'patch-pdf-viewer-css',
    enforce: 'pre' as const,
    transform(code: string, id: string) {
      if (!id.endsWith('/pdf_viewer.css')) return null;
      return code
        .replace('url(images/altText_add.svg)', 'none')
        .replace('url(images/altText_done.svg)', 'none');
    },
  };
}

export default defineConfig({
  plugins: [react(), patchPdfViewerCss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '127.0.0.1',
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
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      onwarn(warning, warn) {
        if (
          warning.code === 'EVAL' &&
          typeof warning.id === 'string' &&
          /pdfjs-dist\/(?:legacy\/)?build\/pdf\.js$/.test(warning.id)
        ) {
          return;
        }
        warn(warning);
      },
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('pdfjs-dist')) return 'pdf';
            if (
              id.includes('react-markdown') ||
              id.includes('remark-gfm') ||
              id.includes('remark-math') ||
              id.includes('rehype-highlight') ||
              id.includes('rehype-katex') ||
              id.includes('katex')
            ) {
              return 'markdown';
            }
            if (
              id.includes('react-router-dom') ||
              id.includes('react-dom') ||
              id.includes('/node_modules/react/')
            ) {
              return 'vendor';
            }
          }

          if (
            id.includes('/src/pages/Workbench') ||
            id.includes('/src/components/PdfViewer') ||
            id.includes('/src/components/AnalysisPanel') ||
            id.includes('/src/components/ChatPanel') ||
            id.includes('/src/components/FigureGallery') ||
            id.includes('/src/components/TableGallery') ||
            id.includes('/src/components/MermaidRenderer') ||
            id.includes('/src/hooks/useAnalysis')
          ) {
            return 'workbench';
          }
        },
      },
    },
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'lucide-react'],
  },
  base: './',
});
