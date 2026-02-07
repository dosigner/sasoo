/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_WS_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

// Electron API type declaration for renderer process
interface Window {
  electronAPI: import('../electron/preload').ElectronAPI;
}
