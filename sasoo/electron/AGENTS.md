<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-02-07 | Updated: 2026-02-07 -->

# Electron Desktop Wrapper

This guide helps AI agents understand the Electron desktop wrapper for Sasoo. Sasoo is an AI Co-Scientist desktop application for academic paper analysis. The Electron layer manages the BrowserWindow, bridges frontend-backend communication via IPC, and controls the Python FastAPI backend lifecycle.

---

## Purpose

The Electron module is responsible for:

1. **Desktop UI Container** - Create and manage the main BrowserWindow displaying the React frontend
2. **Frontend-Backend Bridge** - Route IPC messages between renderer process (React) and main process (Python backend)
3. **Native OS Integration** - File dialogs, path resolution, application lifecycle
4. **Backend Process Management** - Spawn, monitor, and gracefully shutdown the Python FastAPI server
5. **Security Enforcement** - Context isolation, preload scripts, no Node.js integration in renderer

---

## Architecture Overview

```
Electron Desktop App
│
├── Main Process (main.ts)
│   ├── Creates BrowserWindow (1400x900)
│   ├── IPC handlers (file I/O, API proxies)
│   └── App lifecycle (ready, quit, activate)
│
├── Renderer Process (React Frontend)
│   └── Uses preload.ts API (window.electronAPI)
│
├── Preload Script (preload.ts)
│   └── Context bridge exposing safe APIs via contextBridge
│
└── Python Backend Manager (python-manager.ts)
    ├── Spawns FastAPI uvicorn process
    ├── Health monitoring (30s intervals)
    └── Auto-restart on crash (exponential backoff)
```

### Security Model

**Context Isolation: ON**
- Renderer process cannot access Node.js APIs directly
- All renderer↔main communication goes through preload.ts IPC channels
- Frontend accesses backend via `window.electronAPI.*` methods

**Node Integration: OFF**
- Renderer cannot use `require()` or access Node.js
- Main process isolation prevents malicious frontend code from accessing OS

---

## Key Files

### 1. main.ts (11 KB)

**Purpose:** Electron main process entry point. Creates BrowserWindow, registers IPC handlers, manages app lifecycle.

**Key Responsibilities:**

| Responsibility | Implementation |
|----------------|-----------------|
| Window Creation | `createWindow()` - Creates 1400x900 BrowserWindow with dark theme (#0f172a) |
| Dev Server | Loads Vite dev server (http://localhost:5173) in dev mode |
| Production Bundle | Loads bundled frontend from frontend/dist/index.html |
| IPC Handlers | `registerIpcHandlers()` - Registers all IPC channels |
| App Lifecycle | `app.whenReady()`, `window-all-closed`, `activate`, `before-quit` |
| Security | Context isolation enabled, preload script, no nodeIntegration |

**IPC Handlers Registered:**

| Channel | Type | Purpose |
|---------|------|---------|
| `dialog:openFile` | async | Open file picker for PDF selection |
| `dialog:saveFile` | async | Save file picker dialog |
| `file:read` | async | Read file as base64 buffer |
| `file:readText` | async | Read file as UTF-8 text |
| `file:write` | async | Write text to file |
| `papers:upload` | async | Upload PDF file to backend (multipart/form-data) |
| `papers:getAll` | async | Fetch all papers from backend API |
| `papers:get` | async | Fetch single paper by ID |
| `papers:delete` | async | Delete paper from library |
| `analysis:run` | async | Trigger analysis on backend |
| `analysis:getStatus` | async | Check analysis progress |
| `settings:get` | async | Fetch app settings from backend |
| `settings:update` | async | Update app settings on backend |
| `backend:health` | async | Check Python backend health status |
| `app:getInfo` | async | Get app version, platform, Electron version |
| `app:getPath` | async | Get user data paths (userData, appData, etc.) |

**Backend Proxying:**
All API handlers proxy to `http://localhost:8000`:
```typescript
// Example: papers:getAll handler
fetch('http://localhost:8000/api/papers')
```

**Window Configuration:**
```typescript
new BrowserWindow({
  width: 1400,
  height: 900,
  minWidth: 1024,
  minHeight: 680,
  backgroundColor: '#0f172a',
  webPreferences: {
    preload: getPreloadPath(),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: false,
    webSecurity: true,
  }
})
```

---

### 2. preload.ts (4.5 KB)

**Purpose:** Preload script for context isolation. Exposes safe IPC APIs to renderer process via contextBridge.

**Key Responsibilities:**

| Responsibility | Implementation |
|----------------|-----------------|
| API Definition | `ElectronAPI` interface - TypeScript-typed API surface |
| IPC Bridging | Wraps `ipcRenderer.invoke()` calls via contextBridge |
| Type Safety | Full TypeScript types for all methods and return values |
| Event Listeners | Allowlisted channels for bidirectional communication |
| Global Type | Augments `window` interface with `electronAPI` property |

**Exposed API - File Operations:**

```typescript
// File dialogs
openFile(options?) → Promise<{ canceled, filePaths, files }>
saveFile(options?) → Promise<{ canceled, filePath }>

// File I/O
readFile(filePath) → Promise<{ success, data (base64), size }>
readFileText(filePath) → Promise<{ success, data (string) }>
writeFile(filePath, data) → Promise<{ success }>
```

**Exposed API - Papers:**

```typescript
getPapers() → Promise<ApiResult>
getPaper(paperId) → Promise<ApiResult>
uploadPaper(filePath) → Promise<ApiResult>
deletePaper(paperId) → Promise<ApiResult>
```

**Exposed API - Analysis:**

```typescript
runAnalysis(payload: {paperId, analysisType, options?}) → Promise<ApiResult>
getAnalysisStatus(analysisId) → Promise<ApiResult>
```

**Exposed API - Settings & App:**

```typescript
getSettings() → Promise<ApiResult>
updateSettings(settings) → Promise<ApiResult>
checkBackendHealth() → Promise<{ healthy, error? }>
getAppInfo() → Promise<AppInfo>
getAppPath(name) → Promise<string | null>
```

**Event Listeners (Allowlisted Channels):**

```typescript
on(channel, callback) → unsubscribe function

// Allowed channels:
// - analysis:progress
// - analysis:complete
// - analysis:error
// - backend:status
// - app:update-available
```

**Type Definitions:**

All types exported for frontend use:
- `FileInfo` - File metadata
- `OpenFileResult` - File picker result
- `SaveFileResult` - Save dialog result
- `FileReadResult` - File read result
- `ApiResult<T>` - Generic API response wrapper
- `AppInfo` - Application information
- `AnalysisPayload` - Analysis request payload
- `ElectronAPI` - Complete API interface

**Usage in Frontend:**

```typescript
// In React component
const result = await window.electronAPI.openFile({
  title: 'Select PDF',
  filters: [{ name: 'PDFs', extensions: ['pdf'] }],
  multiSelections: false,
});
```

---

### 3. python-manager.ts (9 KB)

**Purpose:** Manages Python FastAPI backend as child process. Handles process lifecycle, health monitoring, and auto-restart.

**Key Responsibilities:**

| Responsibility | Implementation |
|----------------|-----------------|
| Python Discovery | `resolvePythonPath()` - Finds venv or system python |
| Process Spawning | `start()` - Spawns uvicorn with FastAPI server |
| Health Checks | `checkHealth()` - Polls `/health` endpoint (30s interval) |
| Auto-Restart | `handleCrash()` - Restarts with exponential backoff on failure |
| Graceful Shutdown | `stop()` - Sends SIGINT/SIGTERM, force kills after 5s timeout |
| Process Monitoring | Logs stdout/stderr, captures exit codes |

**Configuration (PythonManagerConfig):**

```typescript
interface PythonManagerConfig {
  backendPath: string;        // Path to backend/ directory
  port: number;               // Port to run server (default: 8000)
  isDev: boolean;             // Enable reload on file changes
  pythonPath?: string;        // Custom python executable path
  maxRestartAttempts?: number;     // Max auto-restarts (default: 5)
  healthCheckIntervalMs?: number;  // Health check frequency (default: 30000)
  healthCheckTimeoutMs?: number;   // Health check timeout (default: 5000)
  startupTimeoutMs?: number;       // Max time to wait for startup (default: 30000)
}
```

**Python Path Resolution (Priority Order):**

1. Explicit `pythonPath` in config
2. Virtual environment paths:
   - `.venv/bin/python` (Linux/macOS)
   - `.venv/Scripts/python.exe` (Windows)
   - `venv/bin/python` (Linux/macOS)
   - `venv/Scripts/python.exe` (Windows)
3. System `python3` (Linux/macOS) or `python` (Windows)

**Startup Process:**

1. Resolve Python executable
2. Spawn uvicorn process: `python -m uvicorn main:app --host 127.0.0.1 --port 8000`
3. Poll `/health` endpoint until responsive (max 30s)
4. Start periodic health checks (every 30s)
5. Return success

**Environment Variables Passed to Python:**

```typescript
{
  ...process.env,
  PYTHONUNBUFFERED: '1',           // Unbuffered output
  SASOO_PORT: '8000',              // Server port
  SASOO_ENV: 'development|production'  // Environment flag
}
```

**Uvicorn Arguments (Development):**

```
python -m uvicorn main:app
  --host 127.0.0.1
  --port 8000
  --log-level debug
  --reload
```

**Uvicorn Arguments (Production):**

```
python -m uvicorn main:app
  --host 127.0.0.1
  --port 8000
  --log-level info
```

**Health Check Mechanism:**

```typescript
async checkHealth(): Promise<boolean>
  // Polls: GET http://127.0.0.1:8000/health
  // Returns: true if response.ok, false if timeout or error
  // Timeout: 5 seconds per request
```

**Auto-Restart Logic:**

- **Trigger:** Process exits with non-zero code, or health check fails
- **Strategy:** Exponential backoff (1s, 2s, 4s, 8s, 16s)
- **Max Attempts:** 5 restarts before giving up
- **Logging:** Console logs show attempt number and delay

**Process Output:**

- **stdout** - Logged as `[FastAPI] message`
- **stderr** - Logged as `[FastAPI:err] message`
- **Process Exits** - Logged with exit code and signal
- **Crashes** - Logged with restart attempt number

**Public Methods:**

```typescript
start(): Promise<void>        // Start the backend
stop(): Promise<void>         // Gracefully stop
restart(): Promise<void>      // Restart (stop then start)
isRunning(): boolean          // Check if process alive
getPort(): number             // Get configured port
checkHealth(): Promise<boolean> // Poll /health endpoint
```

**Shutdown Flow:**

1. Mark `isShuttingDown = true` (prevents auto-restart)
2. Stop health check timer
3. Send graceful kill signal (SIGINT on Unix, SIGTERM on Windows)
4. Wait for process exit (5 second timeout)
5. Force kill with SIGKILL if timeout exceeded
6. Log completion

---

### 4. tsconfig.json

**Purpose:** TypeScript compiler configuration for Electron source files.

**Key Settings:**

```typescript
{
  "compilerOptions": {
    "target": "ES2022",           // Compile to ES2022
    "module": "commonjs",          // CommonJS output for Node.js
    "lib": ["ES2022"],             // ES2022 standard library
    "outDir": "../dist-electron",  // Output to monorepo dist-electron/
    "rootDir": ".",                // Source root
    "strict": true,                // Strict type checking enabled
    "esModuleInterop": true,       // ES module interop
    "sourceMap": true,             // Generate .map files for debugging
    "moduleResolution": "node",    // Node.js module resolution
  },
  "include": ["./**/*.ts"],        // Include all .ts files
  "exclude": ["node_modules"]      // Exclude node_modules
}
```

**Compilation Output:**

```
electron/*.ts → dist-electron/*.js
```

Example:
- `electron/main.ts` → `dist-electron/main.js`
- `electron/preload.ts` → `dist-electron/preload.js`
- `electron/python-manager.ts` → `dist-electron/python-manager.js`

---

## IPC Communication Flow

### Request-Response Pattern (Async)

**Frontend → Main → Backend:**

```
1. Frontend calls: window.electronAPI.getPapers()
2. Preload: ipcRenderer.invoke('papers:getAll')
3. Main: ipcMain.handle('papers:getAll', handler)
4. Handler: fetch('http://localhost:8000/api/papers')
5. Main: JSON response from backend
6. Frontend: Promise resolves with data
```

**Code Example:**

```typescript
// Frontend (React component)
const papers = await window.electronAPI.getPapers();

// Preload
getPapers: () => ipcRenderer.invoke('papers:getAll')

// Main
ipcMain.handle('papers:getAll', async () => {
  const response = await fetch('http://localhost:8000/api/papers');
  return await response.json();
});
```

### Event Pattern (Bidirectional)

**Backend → Main → Frontend:**

```
1. Backend emits event via WebSocket or server-sent event
2. Main listens and forwards: ipcRenderer.send('channel', data)
3. Frontend: window.electronAPI.on('channel', callback)
```

**Allowed Event Channels:**

- `analysis:progress` - Analysis progress update
- `analysis:complete` - Analysis finished
- `analysis:error` - Analysis error
- `backend:status` - Backend status change
- `app:update-available` - Update available notification

---

## Development Workflow

### Building

**TypeScript Compilation:**

```bash
cd /home/dosigner/논문/sasoo
pnpm build:electron
# Compiles: electron/*.ts → dist-electron/*.js
```

**Watch Mode (Development):**

```bash
pnpm dev:electron:watch
# Watches electron/*.ts, rebuilds on changes
```

### Running

**Development Mode (with Hot Reload):**

```bash
pnpm dev
# Starts:
# - Vite dev server (port 5173)
# - Electron with live reload
# - Python backend (port 8000)
```

**Launch Electron Manually:**

```bash
pnpm dev:electron
# Compiles and launches Electron app with DevTools
```

### Testing IPC Channels

**Frontend Testing (Browser Console in DevTools):**

```typescript
// Check if API available
console.log(window.electronAPI);

// Test file dialog
const result = await window.electronAPI.openFile();
console.log(result);

// Test backend health
const health = await window.electronAPI.checkBackendHealth();
console.log(health);

// Test app info
const info = await window.electronAPI.getAppInfo();
console.log(info);
```

**Main Process Testing (DevTools Console):**

- Electron shows DevTools by default in dev mode
- Use "Main" tab to see main process logs
- Set breakpoints in main.ts IPC handlers

**Backend Testing:**

```bash
cd backend
python main.py
# FastAPI server on http://localhost:8000
# Docs at http://localhost:8000/docs
```

---

## Common Development Tasks

### Add a New IPC Channel

1. **Define handler in main.ts:**

```typescript
ipcMain.handle('feature:doSomething', async (_event, payload) => {
  // Validate payload
  // Call backend or perform file operation
  const response = await fetch('http://localhost:8000/api/feature/do-something', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return await response.json();
});
```

2. **Add type to preload.ts:**

```typescript
export interface ElectronAPI {
  // ... existing methods
  doSomething: (payload: SomeType) => Promise<ApiResult>;
}
```

3. **Implement in preload.ts:**

```typescript
const electronAPI: ElectronAPI = {
  // ... existing methods
  doSomething: (payload) => ipcRenderer.invoke('feature:doSomething', payload),
};
```

4. **Use in frontend:**

```typescript
const result = await window.electronAPI.doSomething(data);
```

### Debug IPC Issues

**Check Handler Registration:**

```typescript
// In main.ts, after registerIpcHandlers()
console.log('[Main] IPC handlers registered');

// In handler
ipcMain.handle('channel:name', async (event, ...args) => {
  console.log('[Main] Channel called:', { args });
  // ... handler logic
  console.log('[Main] Channel returning:', result);
  return result;
});
```

**Frontend Logging:**

```typescript
// In React component
const result = await window.electronAPI.methodName(arg);
console.log('[Frontend] Result:', result);
```

**Preload Logging:**

```typescript
// In preload.ts
const electronAPI: ElectronAPI = {
  methodName: (arg) => {
    console.log('[Preload] methodName called with:', arg);
    return ipcRenderer.invoke('channel:name', arg);
  },
};
```

### Test Backend Communication

```typescript
// In main.ts handler
ipcMain.handle('test:backend', async () => {
  try {
    console.log('[Main] Testing backend...');
    const response = await fetch('http://localhost:8000/health');
    const data = await response.json();
    console.log('[Main] Backend healthy:', data);
    return { success: true, data };
  } catch (error) {
    console.error('[Main] Backend error:', error);
    return { success: false, error: String(error) };
  }
});
```

### Debug Python Manager

```typescript
// In main.ts initialization
pythonManager = new PythonManager({
  backendPath: getBackendPath(),
  port: 8000,
  isDev,
  // Add custom logging
});

console.log('[Main] PythonManager config:', {
  backendPath: getBackendPath(),
  isDev,
});

await pythonManager.start();
console.log('[Main] PythonManager started');
```

---

## Important Security Notes

### Context Isolation Must Stay Enabled

```typescript
webPreferences: {
  contextIsolation: true,  // ← MUST BE TRUE
  nodeIntegration: false,  // ← MUST BE FALSE
  preload: getPreloadPath(),
}
```

**Why:** Prevents renderer process from accessing Node.js APIs or executing arbitrary OS commands.

### IPC Channels Are the Only Bridge

- Renderer cannot call Node.js `require()` directly
- All OS interactions go through main process IPC handlers
- Main process validates all IPC payloads before processing

### File Dialogs Are Trusted

```typescript
dialog.showOpenDialog(mainWindow, options)
```

User can only select files via native OS dialogs (cannot programmatically access arbitrary files).

### Backend Bound to Localhost

```typescript
fetch('http://127.0.0.1:8000/...')
```

Backend never exposed on network interface (only localhost), preventing remote access.

---

## Dependencies

### Electron Specific

| Package | Version | Purpose |
|---------|---------|---------|
| `electron` | ^28.2.1 | Desktop framework |
| `electron-builder` | ^24.13.3 | App packaging (dev dependency) |

### Node.js Standard Library

- `child_process` (python-manager.ts) - Spawn Python subprocess
- `path` (all files) - Cross-platform path handling
- `fs` (all files) - File system operations

### Electron APIs Used

- `app` - Application lifecycle
- `BrowserWindow` - Desktop window management
- `ipcMain` - Main process IPC handlers
- `dialog` - File dialogs
- `protocol` - Custom protocol registration (imported but not used)

---

## For AI Agents

### Code Organization Patterns

**Main Process (main.ts):**
- `createWindow()` - Window initialization and loading
- `getPreloadPath()`, `getIconPath()`, `getBackendPath()` - Path helpers
- `registerIpcHandlers()` - All IPC handler registration
- `initialize()` - App startup sequence
- App lifecycle listeners (ready, activate, window-all-closed, before-quit)

**IPC Handler Pattern:**
```typescript
ipcMain.handle('namespace:action', async (_event, ...args) => {
  try {
    // Validate input
    // Perform action (file I/O, backend call, etc.)
    // Return result
    return { success: true, data };
  } catch (error) {
    return { success: false, error: String(error) };
  }
});
```

**Preload Script (preload.ts):**
- Type definitions (interfaces for API surface)
- `electronAPI` object wrapping ipcRenderer calls
- `contextBridge.exposeInMainWorld()` to expose API
- Global type augmentation for window.electronAPI

**Python Manager (python-manager.ts):**
- Configuration and state management
- Lifecycle methods (start, stop, restart)
- Health checking with polling
- Error handling with exponential backoff
- Process monitoring (stdout/stderr logging)

### Common Debugging Scenarios

| Scenario | Steps |
|----------|-------|
| IPC call returns error | Check main.ts handler for exception logging, verify backend is running |
| File dialog doesn't appear | Verify mainWindow exists before calling dialog, check event loop |
| Python backend won't start | Check backend path is correct, Python executable exists, uvicorn installed |
| DevTools won't open | Set `mainWindow.webContents.openDevTools()` in createWindow() |
| Changes don't reload | Run `pnpm dev`, check Vite dev server is running on 5173 |

### Key Navigation

| Task | File(s) |
|------|---------|
| Add IPC channel | `main.ts` (handler) → `preload.ts` (API method + type) |
| Change window size/theme | `main.ts` (BrowserWindow constructor) |
| Configure backend startup | `main.ts` (initialize function) or `python-manager.ts` |
| Add file operation | `main.ts` (ipcMain.handle) |
| Debug backend connection | `main.ts` (analyze fetch calls) |
| Test IPC in browser | DevTools Console → call `window.electronAPI.*` |

---

## Version Information

| Tool | Version | Notes |
|------|---------|-------|
| Electron | ^28.2.1 | Desktop framework |
| TypeScript | ^5.3+ | Source language |
| Node.js | 16+ | Runtime (for Electron) |
| Python | 3.9+ | Backend requirement |

---

## Build Artifacts

**Source:**
```
electron/
├── main.ts
├── preload.ts
├── python-manager.ts
└── tsconfig.json
```

**Compiled Output:**
```
dist-electron/
├── main.js (+ main.js.map)
├── preload.js (+ preload.js.map)
└── python-manager.js (+ python-manager.js.map)
```

**Bundled in App:**
- `dist-electron/main.js` - Electron main process
- `frontend/dist/` - React UI (loaded in BrowserWindow)
- `backend/` - Python FastAPI server (spawned as subprocess)

---

## Related Documentation

- **Parent Guide:** `/home/dosigner/논문/sasoo/AGENTS.md`
- **Frontend Guide:** `/home/dosigner/논문/sasoo/frontend/AGENTS.md`
- **Backend Guide:** `/home/dosigner/논문/sasoo/backend/AGENTS.md`
- **Project PRD:** `/home/dosigner/논문/sasoo/PRD_Sasoo_v3.0.md`

---

Last updated: 2026-02-07
