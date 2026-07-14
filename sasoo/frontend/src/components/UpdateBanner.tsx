import { useState, useEffect, useCallback } from 'react';
import { Download, RefreshCw, ExternalLink, X } from 'lucide-react';

type UpdateState = 'hidden' | 'available' | 'downloading' | 'ready';

export default function UpdateBanner() {
  const [state, setState] = useState<UpdateState>('hidden');
  const [version, setVersion] = useState('');
  const [progress, setProgress] = useState(0);
  const [dismissed, setDismissed] = useState(false);

  const isMac = navigator.platform.toLowerCase().includes('mac');

  useEffect(() => {
    if (!window.electronAPI?.on) return;

    const unsubs = [
      window.electronAPI.on('app:update-available', (...args: unknown[]) => {
        const info = args[0] as { version: string };
        setVersion(info.version);
        setState('available');
        setDismissed(false);
      }),
      window.electronAPI.on('app:update-progress', (...args: unknown[]) => {
        const p = args[0] as { percent: number };
        setProgress(Math.round(p.percent));
      }),
      window.electronAPI.on('app:update-downloaded', () => {
        setState('ready');
      }),
    ];

    return () => unsubs.forEach((u) => u());
  }, []);

  const handleDownload = useCallback(async () => {
    if (isMac) {
      // macOS: open release page (no code signing)
      await window.electronAPI?.downloadUpdate();
      return;
    }
    setState('downloading');
    setProgress(0);
    await window.electronAPI?.downloadUpdate();
  }, [isMac]);

  const handleInstall = useCallback(() => {
    window.electronAPI?.installUpdate();
  }, []);

  if (state === 'hidden' || dismissed) return null;

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-accent/10 border-b border-accent/20 text-sm shrink-0">
      <div className="flex-1 min-w-0 flex items-center gap-2">
        {state === 'available' && (
          <>
            <Download className="w-3.5 h-3.5 text-accent shrink-0" />
            <span className="text-fg truncate">
              새 버전 <strong className="text-accent">v{version}</strong>, 지금 받을 수 있어요
            </span>
          </>
        )}
        {state === 'downloading' && (
          <>
            <RefreshCw className="w-3.5 h-3.5 text-accent shrink-0 animate-spin" />
            <span className="text-fg">다운로드 중... {progress}%</span>
            <div className="flex-1 max-w-48 h-1.5 bg-surface rounded-full overflow-hidden">
              <div
                className="h-full w-full bg-accent transition-transform duration-300 ease-out"
                style={{ transformOrigin: 'left', transform: `scaleX(${progress / 100})` }}
              />
            </div>
          </>
        )}
        {state === 'ready' && (
          <>
            <Download className="w-3.5 h-3.5 text-success shrink-0" />
            <span className="text-fg">
              <strong className="text-success">v{version}</strong> 다운로드 완료
            </span>
          </>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 shrink-0">
        {state === 'available' && (
          <button
            onClick={handleDownload}
            className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-accent hover:bg-accent-hover text-accent-fg text-xs font-medium transition-colors"
          >
            {isMac ? (
              <>
                <ExternalLink className="w-3 h-3" />
                릴리즈 페이지
              </>
            ) : (
              <>
                <Download className="w-3 h-3" />
                다운로드
              </>
            )}
          </button>
        )}
        {state === 'ready' && (
          <button
            onClick={handleInstall}
            className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-success text-accent-fg hover:bg-success/90 text-xs font-medium transition-colors"
          >
            <RefreshCw className="w-3 h-3" />
            재시작하여 설치
          </button>
        )}
        {state !== 'downloading' && (
          <button
            onClick={() => setDismissed(true)}
            className="p-1 rounded text-fg-muted hover:text-fg-secondary hover:bg-surface-hover/50 transition-colors"
            aria-label="닫기"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
