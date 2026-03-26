import { useState, useEffect, useCallback } from 'react';
import {
  Loader2,
} from 'lucide-react';
import {
  getSettings,
  updateSettings,
  type Settings as SettingsType,
} from '@/lib/api';
import CostDashboard from '@/components/CostDashboard';
import { useToast } from '@/components/Toast';
import { Toggle } from '@/components/ui';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';

function SettingPanel({
  kicker,
  title,
  description,
  children,
}: {
  kicker: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="archive-panel panel-compact">
      <div className="mb-4">
        <div className="archive-kicker">{kicker}</div>
        <h2 className="settings-panel-title mt-2 text-xl font-semibold tracking-[-0.04em]">
          {title}
        </h2>
        <p className="settings-panel-description mt-2 max-w-2xl text-sm leading-6">
          {description}
        </p>
      </div>
      {children}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  // Form state
  const [geminiKey, setGeminiKey] = useState('');
  const [claudeKey, setClaudeKey] = useState('');
  const [libraryPath, setLibraryPath] = useState('');
  const [theme, setTheme] = useState<'dark' | 'light'>('light');
  const [autoAnalyze, setAutoAnalyze] = useState(false);
  const [pdfParserMode, setPdfParserMode] = useState<'java'>('java');
  const [extractionPipelineVersion, setExtractionPipelineVersion] = useState<'legacy' | 'resolver_v1'>('resolver_v1');

  // API key status (masked value from server, for display only)
  const [geminiKeyStatus, setGeminiKeyStatus] = useState('');
  const [claudeKeyStatus, setClaudeKeyStatus] = useState('');

  // Visibility toggles
  const [showGeminiKey, setShowGeminiKey] = useState(false);
  const [showClaudeKey, setShowClaudeKey] = useState(false);

  // -----------------------------------------------------------------------
  // Load settings
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      try {
        const data = await getSettings();
        if (cancelled) return;
        setSettings(data);
        // Store masked keys for status display, but DON'T populate inputs
        setGeminiKeyStatus(data.gemini_api_key || '');
        setClaudeKeyStatus(data.anthropic_api_key || '');
        // Key inputs start empty — user types new key only when they want to change
        setGeminiKey('');
        setClaudeKey('');
        setLibraryPath(data.library_path || '');
        setTheme(data.theme || 'light');
        setAutoAnalyze(data.auto_analyze ?? false);
        setPdfParserMode(data.pdf_parser_mode || 'java');
        setExtractionPipelineVersion(data.extraction_pipeline_version || 'resolver_v1');
      } catch (err) {
        if (!cancelled) {
          if (err instanceof Error) console.warn('[settings] load error:', err.message);
          setError(S.settings.loadFailed);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadSettings();
    return () => {
      cancelled = true;
    };
  }, []);

  // -----------------------------------------------------------------------
  // Apply theme
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (theme === 'light') {
      document.documentElement.classList.add('light');
      document.documentElement.classList.remove('dark');
    } else {
      document.documentElement.classList.add('dark');
      document.documentElement.classList.remove('light');
    }
    localStorage.setItem('sasoo-theme', theme);
  }, [theme]);

  // -----------------------------------------------------------------------
  // Save settings
  // -----------------------------------------------------------------------
  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaved(false);

    try {
      // Only include API keys if user actually typed new ones
      const payload: Partial<SettingsType> = {
        library_path: libraryPath,
        theme,
        auto_analyze: autoAnalyze,
        pdf_parser_mode: pdfParserMode,
        extraction_pipeline_version: extractionPipelineVersion,
      };
      if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
      if (claudeKey.trim()) payload.anthropic_api_key = claudeKey.trim();

      const updated = await updateSettings(payload);
      setSettings(updated);
      // Update status badges with new masked values
      setGeminiKeyStatus(updated.gemini_api_key || '');
      setClaudeKeyStatus(updated.anthropic_api_key || '');
      // Clear key inputs after save
      setGeminiKey('');
      setClaudeKey('');
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      toast.success(S.toast.settingsSaved);
    } catch (err) {
      setError(S.settings.saveFailed);
      if (err instanceof Error) console.warn('[settings] save error:', err.message);
      toast.error(S.toast.settingsFailed);
    } finally {
      setSaving(false);
    }
  }, [geminiKey, claudeKey, libraryPath, theme, autoAnalyze, pdfParserMode, extractionPipelineVersion, toast]);

  // -----------------------------------------------------------------------
  // Check for unsaved changes
  // -----------------------------------------------------------------------
  const hasChanges =
    settings &&
    (geminiKey.trim() !== '' ||
      claudeKey.trim() !== '' ||
      libraryPath !== (settings.library_path || '') ||
      theme !== (settings.theme || 'light') ||
      autoAnalyze !== (settings.auto_analyze ?? false) ||
      pdfParserMode !== (settings.pdf_parser_mode || 'java') ||
      extractionPipelineVersion !== (settings.extraction_pipeline_version || 'resolver_v1'));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 text-primary-400 animate-spin" />
          <span className="text-sm text-surface-400">{S.settings.loadingSettings}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container-compact">
      <section className="archive-panel panel-compact mb-4">
        <div className="page-header-dense">
          <div>
            <div className="archive-kicker">{S.settings.heroKicker}</div>
            <h1 className="settings-hero-title mt-2 text-[1.8rem] font-semibold tracking-[-0.05em]">
              {S.settings.title}
            </h1>
            <p className="settings-hero-body mt-2 text-sm leading-6">
              {S.settings.heroBody}
            </p>
            <div className="page-status-strip mt-3">
              <span className="archive-inline-status archive-inline-status-muted">
                {S.settings.apiKeys} {geminiKeyStatus || claudeKeyStatus ? S.settings.statusConfigured : S.settings.statusMissing}
              </span>
              <span className="archive-inline-status archive-inline-status-muted">
                {S.settings.librarySection} {libraryPath ? S.settings.statusConfigured : S.settings.statusMissing}
              </span>
              <span className="archive-inline-status archive-inline-status-muted">
                {S.settings.appearance} {theme === 'light' ? S.settings.light : S.settings.dark}
              </span>
            </div>
          </div>
        </div>
      </section>

      {error && (
        <div className="mb-4 archive-inline-status archive-inline-status-error">
          <AppIcon name="warning" className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="space-y-4">
        <SettingPanel
          kicker={S.settings.sectionCurrent}
          title={S.settings.apiKeys}
          description="현재 연결 상태를 먼저 확인하고, 바꿀 키만 새로 입력합니다."
        >
          <div className="space-y-4">
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <label className="text-xs text-surface-400">
                  {S.settings.geminiKey}
                </label>
                {geminiKeyStatus ? (
                  <span className="text-2xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                    {S.settings.keyConfigured} ({geminiKeyStatus})
                  </span>
                ) : (
                  <span className="text-2xs text-amber-400 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded">
                    {S.settings.keyNotConfigured}
                  </span>
                )}
              </div>
              <div className="relative">
                <input
                  type={showGeminiKey ? 'text' : 'password'}
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  placeholder={S.settings.enterNewKey}
                  className="input pr-10"
                />
                <button
                  onClick={() => setShowGeminiKey(!showGeminiKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-surface-500 hover:text-surface-300 transition-colors"
                  style={{ borderRadius: 'var(--radius-control)' }}
                  type="button"
                >
                  {showGeminiKey ? (
                    <AppIcon name="eye-off" className="w-4 h-4" />
                  ) : (
                    <AppIcon name="eye" className="w-4 h-4" />
                  )}
                </button>
              </div>
              <p className="text-2xs text-surface-600 mt-1">
                {S.settings.geminiHelp}{' '}
                <a
                  href="https://aistudio.google.com/api-keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary-400 hover:text-primary-300 underline underline-offset-2"
                >
                  Google AI Studio
                </a>
                {S.settings.getKeyAt('')}
              </p>
            </div>

            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <label className="text-xs text-surface-400">
                  {S.settings.claudeKey}
                </label>
                {claudeKeyStatus ? (
                  <span className="text-2xs text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 rounded">
                    {S.settings.keyConfigured} ({claudeKeyStatus})
                  </span>
                ) : (
                  <span className="text-2xs text-amber-400 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded">
                    {S.settings.keyNotConfigured}
                  </span>
                )}
              </div>
              <div className="relative">
                <input
                  type={showClaudeKey ? 'text' : 'password'}
                  value={claudeKey}
                  onChange={(e) => setClaudeKey(e.target.value)}
                  placeholder={S.settings.enterNewKey}
                  className="input pr-10"
                />
                <button
                  onClick={() => setShowClaudeKey(!showClaudeKey)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-surface-500 hover:text-surface-300 transition-colors"
                  style={{ borderRadius: 'var(--radius-control)' }}
                  type="button"
                >
                  {showClaudeKey ? (
                    <AppIcon name="eye-off" className="w-4 h-4" />
                  ) : (
                    <AppIcon name="eye" className="w-4 h-4" />
                  )}
                </button>
              </div>
              <p className="text-2xs text-surface-600 mt-1">
                {S.settings.claudeHelp}{' '}
                <a
                  href="https://platform.claude.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary-400 hover:text-primary-300 underline underline-offset-2"
                >
                  Anthropic Console
                </a>
                {S.settings.getKeyAt('')}
              </p>
            </div>
          </div>
        </SettingPanel>

        <SettingPanel
          kicker={S.settings.sectionEdit}
          title={S.settings.librarySection}
          description="논문이 쌓이는 경로와 업로드 직후의 기본 동작을 정리합니다."
        >
          <div className="space-y-4">
            <div>
              <label className="text-xs text-surface-400 block mb-1.5">
                {S.settings.libraryPath}
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={libraryPath}
                  onChange={(e) => setLibraryPath(e.target.value)}
                  placeholder="/path/to/papers"
                  className="input flex-1"
                />
                <button
                  type="button"
                  onClick={async () => {
                    if (window.electronAPI?.openDirectory) {
                      const result = await window.electronAPI.openDirectory({
                        title: S.settings.browseFolderTitle,
                        defaultPath: libraryPath || undefined,
                      });
                      if (!result.canceled && result.directoryPath) {
                        setLibraryPath(result.directoryPath);
                      }
                    }
                  }}
                  className="btn-ghost px-3 shrink-0"
                  title={S.settings.browseFolder}
                >
                  <AppIcon name="folder" className="w-4 h-4" />
                </button>
              </div>
              <p className="text-2xs text-surface-600 mt-1">
                {S.settings.libraryPathHelp}
              </p>
            </div>

            <Toggle
              checked={autoAnalyze}
              onChange={setAutoAnalyze}
              label={S.settings.autoAnalyze}
              description={S.settings.autoAnalyzeHelp}
            />

            <div>
              <label className="text-xs text-surface-400 block mb-1.5">
                {S.settings.pdfParser}
              </label>
              <select
                value={pdfParserMode}
                onChange={(e) => setPdfParserMode(e.target.value as 'java')}
                className="input"
              >
                <option value="java">{S.settings.pdfParserJava}</option>
              </select>
              <p className="text-2xs text-surface-600 mt-1">
                {S.settings.pdfParserHelp}
              </p>
            </div>

            <div>
              <label className="text-xs text-surface-400 block mb-1.5">
                {S.settings.extractionPipeline}
              </label>
              <select
                value={extractionPipelineVersion}
                onChange={(e) => setExtractionPipelineVersion(e.target.value as 'legacy' | 'resolver_v1')}
                className="input"
              >
                <option value="legacy">{S.settings.extractionPipelineLegacy}</option>
                <option value="resolver_v1">{S.settings.extractionPipelineResolverV1}</option>
              </select>
              <p className="text-2xs text-surface-600 mt-1">
                {S.settings.extractionPipelineHelp}
              </p>
            </div>
          </div>
        </SettingPanel>

        <SettingPanel
          kicker={S.settings.sectionEdit}
          title={S.settings.appearance}
          description="현재 작업 환경에 맞게 화면 톤을 조정합니다."
        >
          <div className="flex items-center gap-3">
            <button
              onClick={() => setTheme('dark')}
              className={`settings-appearance-option flex items-center gap-2 px-4 py-3 border transition-colors ${
                theme === 'dark'
                  ? 'settings-appearance-option-active border-primary-500 bg-primary-500/10 text-primary-400'
                  : 'settings-appearance-option-inactive'
              }`}
              style={{ borderRadius: 'var(--radius-control)' }}
            >
              <AppIcon name="moon" className="w-4 h-4" />
              <span className="text-sm">{S.settings.dark}</span>
            </button>
            <button
              onClick={() => setTheme('light')}
              className={`settings-appearance-option flex items-center gap-2 px-4 py-3 border transition-colors ${
                theme === 'light'
                  ? 'settings-appearance-option-active border-primary-500 bg-primary-500/10 text-primary-400'
                  : 'settings-appearance-option-inactive'
              }`}
              style={{ borderRadius: 'var(--radius-control)' }}
            >
              <AppIcon name="sun" className="w-4 h-4" />
              <span className="text-sm">{S.settings.light}</span>
            </button>
          </div>
        </SettingPanel>

        <SettingPanel
          kicker={S.settings.sectionCurrent}
          title={S.settings.usageCosts}
          description="최근 분석이 얼마나 호출과 비용을 만들었는지 확인합니다."
        >
          <CostDashboard />
        </SettingPanel>
      </div>

      {(hasChanges || saved) && (
        <div className="settings-savebar fixed bottom-0 left-0 right-0 z-40 border-t px-5 py-3 backdrop-blur-xl">
          <div className="mx-auto flex max-w-[96rem] items-center justify-between gap-4">
            <div className={saved ? 'archive-inline-status archive-inline-status-success' : 'archive-inline-status archive-inline-status-muted'}>
              {saved ? (
                <AppIcon name="success" className="w-4 h-4" />
              ) : (
                <AppIcon name="info" className="w-4 h-4" />
              )}
              {saved ? S.settings.saved : S.settings.unsavedChanges}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  // Discard: reset to server values
                  setGeminiKey('');
                  setClaudeKey('');
                  if (settings) {
                    setLibraryPath(settings.library_path || '');
                    setTheme(settings.theme || 'light');
                    setAutoAnalyze(settings.auto_analyze ?? false);
                    setPdfParserMode(settings.pdf_parser_mode || 'java');
                    setExtractionPipelineVersion(settings.extraction_pipeline_version || 'resolver_v1');
                  }
                }}
                className="btn-ghost text-sm"
              >
                {S.settings.discard}
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !hasChanges}
                className="btn-primary text-sm"
              >
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <AppIcon name="save" className="w-4 h-4" />
                )}
                {S.settings.save}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
