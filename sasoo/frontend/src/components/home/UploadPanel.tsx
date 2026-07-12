import { useState, useCallback, useRef, useEffect, type CSSProperties } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import {
  ApiError,
  getSettings,
  uploadPaper,
  updatePaper,
  type PaperUpdateData,
  type Settings,
  type UploadResponse,
} from '@/lib/api';
import { getAgentMeta, getAllAgents } from '@/lib/agents';
import { useToast } from '@/components/Toast';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import { Select } from '@/components/ui';
import LevelSlider from '@/components/LevelSlider';

const MAX_FILE_SIZE = 50 * 1024 * 1024;
const ACCEPTED_TYPES = ['application/pdf'];

// 분석 초점 칩 — 다중 선택. key는 백엔드 analysis_focus.chips로 전달된다.
const FOCUS_CHIPS = [
  { key: 'reproduction', label: '재현 방법' },
  { key: 'contribution', label: '핵심 기여' },
  { key: 'limitations', label: '한계·후속 연구' },
  { key: 'theory', label: '수식·이론' },
  { key: 'related_work', label: '선행연구 대비' },
] as const;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type UploadStage = 'idle' | 'uploading' | 'parsing' | 'classified' | 'error';

export default function UploadPanel() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { toast } = useToast();

  const [stage, setStage] = useState<UploadStage>('idle');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [domainOverride, setDomainOverride] = useState<string>('');
  const [focusChips, setFocusChips] = useState<string[]>([]);
  const [focusNote, setFocusNote] = useState('');
  const [levelOverride, setLevelOverride] = useState<string | null>(null); // null = 설정 기본값 사용
  const [analysisOptionsOpen, setAnalysisOptionsOpen] = useState(false);
  const [settingsSnapshot, setSettingsSnapshot] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // 기본 설명 수준(연구자 프로필)을 슬라이더 초기값으로 쓰기 위해 설정을 미리 읽어둔다.
  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((data) => {
        if (!cancelled) setSettingsSnapshot(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleFocusChip = useCallback((key: string) => {
    setFocusChips((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
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
      const updates: PaperUpdateData = {};
      if (domainOverride && domainOverride !== uploadResult.domain) {
        updates.domain = domainOverride;
      }
      if (levelOverride) {
        updates.explanation_level = levelOverride;
      }
      if (focusChips.length > 0 || focusNote.trim()) {
        updates.analysis_focus = { chips: focusChips, note: focusNote.trim() };
      }
      if (Object.keys(updates).length > 0) {
        await updatePaper(uploadResult.id, updates);
      }
      navigate(`/workbench/${uploadResult.id}`);
    } catch {
      navigate(`/workbench/${uploadResult.id}`);
    }
  }, [navigate, uploadResult, domainOverride, levelOverride, focusChips, focusNote]);

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

  return (
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
                      className="agent-tinted mt-5 rounded-surface border p-3"
                      style={{ '--agent-color': displayColor } as CSSProperties}
                    >
                      <div className="flex items-center gap-3">
                        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface/80">
                          <AppIcon name="agents" className="h-5 w-5 text-fg-muted" />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 text-sm font-semibold text-fg">
                            <span className="agent-dot" aria-hidden="true" />
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

              <div className="rounded-surface border border-border bg-surface/60">
                <button
                  type="button"
                  onClick={() => setAnalysisOptionsOpen((open) => !open)}
                  aria-expanded={analysisOptionsOpen}
                  aria-label={
                    analysisOptionsOpen
                      ? S.upload.analysisOptionsCloseLabel
                      : S.upload.analysisOptionsOpenLabel
                  }
                  className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left"
                >
                  <div>
                    <div className="text-sm font-medium text-fg">
                      {S.upload.analysisOptionsTitle}
                    </div>
                    {!analysisOptionsOpen && (
                      <p className="mt-1 text-xs leading-5 text-fg-muted">
                        {S.upload.analysisOptionsHint}
                      </p>
                    )}
                  </div>
                  <AppIcon
                    name="chevron-down"
                    className={`h-4 w-4 shrink-0 text-fg-muted transition-transform duration-200 ${
                      analysisOptionsOpen ? 'rotate-180' : ''
                    }`}
                  />
                </button>

                {analysisOptionsOpen && (
                  <div className="space-y-5 border-t border-border/70 px-4 pb-4 pt-4">
                    <div>
                      <label className="text-2xs uppercase tracking-[0.22em] text-fg-muted">
                        {S.upload.focusChipsLabel}
                      </label>
                      <p className="mt-1 text-xs leading-5 text-fg-muted">
                        {S.upload.focusChipsHelp}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {FOCUS_CHIPS.map((chip) => {
                          const selected = focusChips.includes(chip.key);
                          return (
                            <button
                              key={chip.key}
                              type="button"
                              aria-pressed={selected}
                              onClick={() => toggleFocusChip(chip.key)}
                              className={`inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-sm transition-colors ${
                                selected
                                  ? 'border-accent bg-accent font-semibold text-accent-fg'
                                  : 'border-border bg-surface font-normal text-fg-secondary hover:border-accent/50 hover:text-fg'
                              }`}
                            >
                              {selected && <AppIcon name="success" className="h-3.5 w-3.5" />}
                              {chip.label}
                            </button>
                          );
                        })}
                      </div>
                    </div>

                    <div>
                      <label
                        htmlFor="focus-note"
                        className="text-2xs uppercase tracking-[0.22em] text-fg-muted"
                      >
                        {S.upload.focusNoteLabel}
                      </label>
                      <textarea
                        id="focus-note"
                        value={focusNote}
                        onChange={(e) => setFocusNote(e.target.value)}
                        placeholder={S.upload.focusNotePlaceholder}
                        rows={2}
                        className="input mt-2 resize-none"
                      />
                      <p className="mt-2 text-xs leading-6 text-fg-muted">
                        {S.upload.focusNoteHelper}
                      </p>
                    </div>

                    <div>
                      <label className="text-2xs uppercase tracking-[0.22em] text-fg-muted">
                        {S.explanationLevel.title}
                      </label>
                      <div className="mt-3">
                        <LevelSlider
                          value={levelOverride ?? settingsSnapshot?.default_explanation_level ?? 'masters'}
                          onChange={setLevelOverride}
                          compact
                        />
                      </div>
                    </div>
                  </div>
                )}
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
  );
}
