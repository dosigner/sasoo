import { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import logoImg from '@/assets/logo.png';
import {
  ApiError,
  getPapers,
  getSettings,
  uploadPaper,
  updatePaper,
  type Paper,
  type Settings,
  type UploadResponse,
} from '@/lib/api';
import { getAgentMeta, getAllAgents, agentBgStyle, agentBorderStyle } from '@/lib/agents';
import { useToast } from '@/components/Toast';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import { Select } from '@/components/ui';

const MAX_FILE_SIZE = 50 * 1024 * 1024;
const ACCEPTED_TYPES = ['application/pdf'];

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatPaperDate(dateStr: string | null): string {
  if (!dateStr) return S.upload.noTimestamp;

  return new Date(dateStr).toLocaleDateString('ko-KR', {
    month: 'short',
    day: 'numeric',
  });
}

function paperStatusLabel(status: Paper['status']): string {
  switch (status) {
    case 'completed':
      return S.status.analyzed;
    case 'analyzing':
      return S.status.analyzing;
    case 'error':
      return S.status.error;
    case 'pending':
    default:
      return S.status.pending;
  }
}

function paperStatusClass(status: Paper['status']): string {
  switch (status) {
    case 'completed':
      return 'border-success/20 bg-success/10 text-success';
    case 'analyzing':
      return 'border-accent/20 bg-accent/10 text-accent';
    case 'error':
      return 'border-danger/20 bg-danger/10 text-danger';
    case 'pending':
    default:
      return 'border-warning/20 bg-warning/10 text-warning';
  }
}

function RecentPaperRow({
  paper,
  metaLabel,
  metaValue,
  onOpen,
}: {
  paper: Paper;
  metaLabel: string;
  metaValue: string;
  onOpen: (id: string) => void;
}) {
  const agent = getAgentMeta(paper.agent_used);

  return (
    <button
      type="button"
      onClick={() => onOpen(String(paper.id))}
      className="group w-full rounded-surface bg-surface/30 px-4 py-3.5 text-left transition-all duration-200 hover:bg-surface/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
      aria-label={`${paper.title} 워크벤치 열기`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className={`inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-2xs ${paperStatusClass(paper.status)}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {paperStatusLabel(paper.status)}
          </div>
          <h3 className="mt-3 line-clamp-2 text-base font-semibold leading-6 text-fg transition-colors group-hover:text-fg">
            {paper.title}
          </h3>
          <p className="mt-1.5 line-clamp-1 text-sm leading-5 text-fg-muted">
            {paper.authors || paper.journal || paper.domain}
          </p>
        </div>
        <span className="mt-0.5 shrink-0 rounded-full bg-surface/70 p-2 text-fg-muted transition-colors group-hover:text-fg">
          <AppIcon name="arrow-right" className="h-3.5 w-3.5" />
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm leading-5 text-fg-muted">
        <span>{metaLabel} {metaValue}</span>
        <span className="h-1 w-1 rounded-full bg-border" />
        <span>{paper.domain}</span>
        {agent && (
          <>
            <span className="h-1 w-1 rounded-full bg-border" />
            <span>{agent.nameKo}</span>
          </>
        )}
      </div>
    </button>
  );
}

type UploadStage = 'idle' | 'uploading' | 'parsing' | 'classified' | 'error';

export default function Upload() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const [stage, setStage] = useState<UploadStage>('idle');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [domainOverride, setDomainOverride] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [settingsSnapshot, setSettingsSnapshot] = useState<Settings | null>(null);
  const [systemReady, setSystemReady] = useState<boolean | null>(null);
  const [recentAnalyses, setRecentAnalyses] = useState<Paper[]>([]);
  const [recentLibrary, setRecentLibrary] = useState<Paper[]>([]);

  useEffect(() => {
    let cancelled = false;

    getSettings()
      .then((data) => {
        if (cancelled) return;
        setSettingsSnapshot(data);
        setSystemReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setSystemReady(false);
      });

    Promise.all([
      getPapers({
        page: 1,
        page_size: 4,
        sort_by: 'analyzed_at',
        sort_order: 'desc',
      }),
      getPapers({
        page: 1,
        page_size: 4,
        sort_by: 'created_at',
        sort_order: 'desc',
      }),
    ])
      .then(([analysisResponse, libraryResponse]) => {
        if (cancelled) return;
        setRecentAnalyses(analysisResponse.papers.filter((paper) => paper.analyzed_at).slice(0, 4));
        setRecentLibrary(libraryResponse.papers.slice(0, 4));
      })
      .catch(() => {
        if (cancelled) return;
        setRecentAnalyses([]);
        setRecentLibrary([]);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const validateFile = useCallback((file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type) && !file.name.endsWith('.pdf')) {
      return S.upload.onlyPdf;
    }
    if (file.size > MAX_FILE_SIZE) {
      return S.upload.fileTooLarge(formatFileSize(MAX_FILE_SIZE));
    }
    if (file.size === 0) {
      return S.upload.fileEmpty;
    }
    return null;
  }, []);

  const handleFileSelect = useCallback(
    (file: File) => {
      const validationError = validateFile(file);
      if (validationError) {
        setError(validationError);
        return;
      }
      setSelectedFile(file);
      setError(null);
      setStage('idle');
      setUploadResult(null);
    },
    [validateFile]
  );

  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;

    setError(null);
    setStage('uploading');
    setUploadProgress(0);

    try {
      const result = await uploadPaper(selectedFile, (progress) => {
        setUploadProgress(progress);
        if (progress >= 100) setStage('parsing');
      });

      setUploadResult(result);
      setDomainOverride(result.domain);
      setStage('classified');
      toast.success(S.toast.uploadSuccess);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error && err.message
            ? err.message
            : S.upload.uploadFailed;
      setStage('error');
      setError(message);
      if (err instanceof Error) console.warn('[upload] error:', err.message);
      toast.error(message);
    }
  }, [selectedFile, toast]);

  const handleStartAnalysis = useCallback(async () => {
    if (!uploadResult) return;
    try {
      if (domainOverride && domainOverride !== uploadResult.domain) {
        await updatePaper(uploadResult.id, { domain: domainOverride });
      }
      navigate(`/workbench/${uploadResult.id}`);
    } catch {
      navigate(`/workbench/${uploadResult.id}`);
    }
  }, [navigate, uploadResult, domainOverride]);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget === e.target) setIsDragging(false);
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) handleFileSelect(files[0]);
    },
    [handleFileSelect]
  );

  const clearFile = useCallback(() => {
    setSelectedFile(null);
    setUploadResult(null);
    setStage('idle');
    setError(null);
    setUploadProgress(0);
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, []);

  const systemStatusClass =
    systemReady === null
      ? 'archive-inline-status archive-inline-status-muted'
      : systemReady
        ? 'archive-inline-status archive-inline-status-success'
        : 'archive-inline-status archive-inline-status-error';

  const handleOpenRecent = useCallback(
    (id: string) => {
      navigate(`/workbench/${id}`);
    },
    [navigate]
  );

  const systemSummary = [
    {
      label: S.upload.systemLibrary,
      value: settingsSnapshot?.library_path || S.upload.systemNotConfigured,
    },
    {
      label: S.upload.systemAuto,
      value: settingsSnapshot?.auto_analyze ? S.upload.systemAutoOn : S.upload.systemAutoOff,
    },
    {
      label: S.upload.systemTheme,
      value: settingsSnapshot?.theme === 'light' ? S.settings.light : S.settings.dark,
    },
  ];

  return (
    <div className="page-container-wide">
      <section className="page-header-dense mb-4">
        <div>
          <div className="archive-kicker">{S.upload.heroKicker}</div>
          <div className="mt-3 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-border/80 bg-surface/85">
              <img src={logoImg} alt="Sasoo" className="h-7 w-7 rounded-xl" />
            </div>
            <div>
              <h1 className="text-[1.45rem] font-semibold tracking-[-0.05em] text-fg">
                {S.app.name}
              </h1>
              <p className="text-sm text-fg-muted">{S.upload.heroBody}</p>
            </div>
          </div>
        </div>
        <div className="page-status-strip">
          <span className={systemStatusClass}>
            <span className={`h-2 w-2 rounded-full ${systemReady ? 'bg-success' : systemReady === false ? 'bg-warning' : 'bg-fg-muted'}`} />
            {systemReady === null
              ? S.settings.loadingSettings
              : systemReady
                ? S.upload.systemReady
                : S.upload.systemOffline}
          </span>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1.18fr)_minmax(24rem,34rem)]">
        <section
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className={`archive-panel panel-compact relative overflow-hidden ${
            isDragging ? 'border-accent/40 bg-accent/10' : ''
          }`}
        >
          <div className="page-header-dense gap-3 border-b border-border/70 pb-4">
            <div>
              <div className="archive-kicker">{S.upload.surfaceTitle}</div>
              <h2 className="mt-2 text-[1.55rem] font-semibold tracking-[-0.04em] text-fg">
                {selectedFile ? selectedFile.name : S.upload.dragDrop}
              </h2>
              <p className="mt-2 max-w-xl text-sm leading-6 text-fg-muted">
                {selectedFile ? formatFileSize(selectedFile.size) : S.upload.surfaceBody}
              </p>
            </div>
            {!selectedFile && (
              <button
                onClick={() => fileInputRef.current?.click()}
                className="btn-primary shrink-0 justify-center py-3 text-sm"
              >
                <AppIcon name="upload" className="h-4 w-4" />
                {S.upload.uploadBtn}
              </button>
            )}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileSelect(file);
            }}
          />

          {!selectedFile && (
            <div className="mt-4 rounded-surface border border-dashed border-border bg-surface/40 px-4 py-5 transition-colors hover:border-accent/50">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-border/80 bg-surface/90">
                  <AppIcon name="upload" className="h-5 w-5 text-accent" />
                </div>
                <div>
                  <div className="text-sm font-medium text-fg">{S.upload.surfaceActionTitle}</div>
                  <p className="mt-1 text-sm leading-6 text-fg-muted">{S.upload.emptyHint}</p>
                </div>
              </div>
              <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-fg-muted">
                <span>{S.upload.pdfOnly}</span>
                <span className="h-1 w-1 rounded-full bg-border" />
                <span>{S.upload.maxSize(formatFileSize(MAX_FILE_SIZE))}</span>
              </div>
            </div>
          )}

          {selectedFile && (
            <div className="mt-6 space-y-4">
              <div className="rounded-surface border border-border bg-surface/60 p-4">
                <div className="flex items-start gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-surface">
                    <AppIcon name="document" className="h-5 w-5 text-accent" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-fg">{selectedFile.name}</div>
                    <div className="mt-1 text-xs text-fg-muted">{formatFileSize(selectedFile.size)}</div>
                  </div>
                  {stage === 'idle' && (
                    <button
                      onClick={clearFile}
                      className="rounded-full border border-border px-3 py-1.5 text-xs text-fg-muted transition-colors hover:border-border hover:text-fg"
                    >
                      {S.upload.clear}
                    </button>
                  )}
                </div>
              </div>

              {(stage === 'uploading' || stage === 'parsing') && (
                <div className="rounded-surface border border-border bg-surface/60 p-4">
                  <div className="h-2 overflow-hidden rounded-full bg-surface">
                    <div
                      className="h-full rounded-full bg-accent transition-all duration-300"
                      style={{ width: stage === 'parsing' ? '100%' : `${uploadProgress}%` }}
                    />
                  </div>
                  <div className="mt-3 flex items-center gap-2 text-sm text-fg-muted">
                    <Loader2 className="h-4 w-4 animate-spin text-accent" />
                    {stage === 'uploading' ? S.upload.uploading(uploadProgress) : S.upload.parsing}
                  </div>
                </div>
              )}

              {stage === 'classified' && uploadResult && (
                <div className="space-y-4 fade-in-up">
                  <div className="archive-inline-status archive-inline-status-success">
                    <AppIcon name="success" className="h-4 w-4" />
                    {S.upload.handoffTitle}
                  </div>

                <div className="rounded-surface border border-border bg-surface/60 p-4">
                  <div className="text-2xs uppercase tracking-[0.22em] text-fg-muted">
                    {S.upload.titleLabel}
                    </div>
                    <p className="mt-2 text-sm leading-6 text-fg">{uploadResult.title}</p>

                    {(() => {
                      const agent = getAgentMeta(uploadResult.agent_used);
                      const displayName = agent ? agent.name : S.agent.unknownAgent;
                      const displayPersonality = agent ? agent.personality : S.agent.unknownDomain;
                      const displayQuote = agent ? agent.quote : S.agent.fallbackQuote;
                      const displayColor = agent ? agent.color : '#6b7280';

                      return (
                        <div
                          className="mt-5 rounded-surface border p-3"
                          style={{ ...agentBgStyle(displayColor), ...agentBorderStyle(displayColor) }}
                        >
                          <div className="flex items-center gap-3">
                            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface/80">
                              <AppIcon name="agents" className="h-5 w-5 text-fg-muted" />
                            </div>
                            <div className="min-w-0">
                              <div className="text-sm font-semibold" style={{ color: displayColor }}>
                                {displayName}
                              </div>
                              <div className="mt-1 text-xs text-fg-muted">{displayPersonality}</div>
                              <p className="mt-2 text-xs italic text-fg-secondary">"{displayQuote}"</p>
                            </div>
                          </div>
                        </div>
                      );
                    })()}

                    <div className="mt-5">
                      <label className="text-2xs uppercase tracking-[0.22em] text-fg-muted">
                        {S.upload.domainConfirm}
                      </label>
                      <Select
                        value={domainOverride}
                        onValueChange={setDomainOverride}
                        className="mt-2"
                        aria-label={S.upload.domainConfirm}
                        options={getAllAgents().map((agent) => ({
                          value: agent.domain,
                          label: `${agent.domain_display}${agent.domain === uploadResult.domain ? ` ${S.upload.detected}` : ''}`,
                        }))}
                      />
                      <p className="mt-2 text-xs leading-6 text-fg-muted">
                        {S.upload.domainConfirmHelp}
                      </p>
                    </div>
                  </div>

                  <button onClick={handleStartAnalysis} className="btn-primary w-full justify-center py-3 text-sm">
                    {S.upload.openWorkbench}
                    <AppIcon name="arrow-right" className="h-4 w-4" />
                  </button>
                </div>
              )}

              {stage === 'error' && (
                <div className="space-y-4">
                  <div className="archive-inline-status archive-inline-status-error">
                    <AppIcon name="warning" className="h-4 w-4" />
                    {error}
                  </div>
                  <div className="flex gap-2">
                    <button onClick={handleUpload} className="btn-primary flex-1 justify-center">
                      {S.upload.retry}
                    </button>
                    <button onClick={clearFile} className="btn-secondary">
                      {S.upload.clear}
                    </button>
                  </div>
                </div>
              )}

              {stage === 'idle' && (
                <button onClick={handleUpload} className="btn-primary w-full justify-center py-3 text-sm">
                  <AppIcon name="upload" className="h-4 w-4" />
                  {S.upload.uploadBtn}
                </button>
              )}
            </div>
          )}

          {error && stage === 'idle' && (
            <div className="mt-5 archive-inline-status archive-inline-status-error">
              <AppIcon name="warning" className="h-4 w-4" />
              {error}
            </div>
          )}
        </section>

        <div className="grid gap-4">
          <section className="archive-panel panel-compact">
            <div className="archive-kicker">{S.upload.recentAnalyses}</div>
            <div className="mt-3 grid gap-3">
              {recentAnalyses.length > 0 ? (
                recentAnalyses.map((paper) => (
                  <RecentPaperRow
                    key={`recent-analysis-${paper.id}`}
                    paper={paper}
                    metaLabel={S.upload.lastAnalyzed}
                    metaValue={formatPaperDate(paper.analyzed_at)}
                    onOpen={handleOpenRecent}
                  />
                ))
              ) : (
                <div className="rounded-surface bg-surface/30 px-4 py-5 text-sm leading-6 text-fg-muted">
                  {S.upload.recentAnalysesEmpty}
                </div>
              )}
            </div>
          </section>

          <section className="archive-panel panel-compact">
            <div className="archive-kicker">{S.upload.recentLibrary}</div>
            <div className="mt-3 grid gap-3">
              {recentLibrary.length > 0 ? (
                recentLibrary.map((paper) => (
                  <RecentPaperRow
                    key={`recent-library-${paper.id}`}
                    paper={paper}
                    metaLabel={S.upload.addedLabel}
                    metaValue={formatPaperDate(paper.created_at)}
                    onOpen={handleOpenRecent}
                  />
                ))
              ) : (
                <div className="rounded-surface bg-surface/30 px-4 py-5 text-sm leading-6 text-fg-muted">
                  {S.upload.recentLibraryEmpty}
                </div>
              )}
            </div>
          </section>

          <section className="archive-panel panel-compact">
            <div className="archive-kicker">{S.upload.systemTitle}</div>
            <div className="mt-3 grid gap-3">
              {systemSummary.map((item) => (
                <div
                  key={item.label}
                  className="flex items-center justify-between gap-4 rounded-surface bg-surface/30 px-4 py-3"
                >
                  <span className="text-2xs uppercase tracking-[0.16em] text-fg-muted">{item.label}</span>
                  <span className="max-w-[65%] truncate text-right text-base text-fg">{item.value}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
