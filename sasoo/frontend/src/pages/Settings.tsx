import { useState, useEffect, useCallback, useRef } from 'react';
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
import LevelSlider, { type LevelKey } from '@/components/LevelSlider';

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
  const defaultSettings: SettingsType = {
    gemini_api_key: '',
    library_path: '',
    default_domain: 'optics',
    auto_analyze: false,
    language: 'ko',
    theme: 'light',
    max_concurrent_analyses: 3,
    gemini_model: 'gemini-3-flash-preview',
    pdf_parser_mode: 'java',
    extraction_pipeline_version: 'resolver_v1',
    paperbanana_profile: 'fast',
    research_context: '',
    default_explanation_level: 'masters',
  };

  const [baselineSettings, setBaselineSettings] = useState<SettingsType>(defaultSettings);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();

  // Form state
  const [geminiKey, setGeminiKey] = useState('');
  const [libraryPath, setLibraryPath] = useState('');
  const [theme, setTheme] = useState<'dark' | 'light'>('light');
  const [autoAnalyze, setAutoAnalyze] = useState(false);
  const [pdfParserMode, setPdfParserMode] = useState<'java'>('java');
  const [extractionPipelineVersion, setExtractionPipelineVersion] = useState<'legacy' | 'resolver_v1'>('resolver_v1');
  const [researchContext, setResearchContext] = useState('');
  const [defaultLevel, setDefaultLevel] = useState<LevelKey>('masters');

  // API key status (masked value from server, for display only)
  const [geminiKeyStatus, setGeminiKeyStatus] = useState('');

  // Visibility toggles
  const [showGeminiKey, setShowGeminiKey] = useState(false);
  const geminiInputRef = useRef<HTMLInputElement | null>(null);

  const clearApiKeyInputs = useCallback(() => {
    setGeminiKey('');
    if (geminiInputRef.current) geminiInputRef.current.value = '';
  }, []);

  const applySettingsToForm = useCallback((data: SettingsType) => {
    setLibraryPath(data.library_path || '');
    setTheme((data.theme || 'light') as 'dark' | 'light');
    setAutoAnalyze(data.auto_analyze ?? false);
    setPdfParserMode((data.pdf_parser_mode || 'java') as 'java');
    setExtractionPipelineVersion(
      (data.extraction_pipeline_version || 'resolver_v1') as 'legacy' | 'resolver_v1'
    );
    setResearchContext(data.research_context || '');
    setDefaultLevel((data.default_explanation_level || 'masters') as LevelKey);
  }, []);

  // -----------------------------------------------------------------------
  // Load settings
  // -----------------------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    async function loadSettings() {
      try {
        const data = await getSettings();
        if (cancelled) return;
        // Store masked keys for status display, but DON'T populate inputs
        setGeminiKeyStatus(data.gemini_api_key || '');
        // Key inputs start empty — user types new key only when they want to change
        clearApiKeyInputs();
        applySettingsToForm(data);
        setBaselineSettings(data);
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
  }, [applySettingsToForm, clearApiKeyInputs]);

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
        research_context: researchContext,
        default_explanation_level: defaultLevel,
      };
      if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();

      const updated = await updateSettings(payload);
      setBaselineSettings(updated);
      applySettingsToForm(updated);
      // Update status badges with new masked values
      setGeminiKeyStatus(updated.gemini_api_key || '');
      // Clear key inputs after save. This also fights password-manager autofill
      // that can leave the settings screen permanently "dirty".
      clearApiKeyInputs();
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      toast.success(S.toast.settingsSaved);
    } catch (err) {
      setError(err instanceof Error ? err.message : S.settings.saveFailed);
      if (err instanceof Error) console.warn('[settings] save error:', err.message);
      toast.error(S.toast.settingsFailed);
    } finally {
      setSaving(false);
    }
  }, [geminiKey, libraryPath, theme, autoAnalyze, pdfParserMode, extractionPipelineVersion, researchContext, defaultLevel, toast, applySettingsToForm, clearApiKeyInputs]);

  const handleBrowseDirectory = useCallback(async () => {
    if (!window.electronAPI?.openDirectory) {
      toast.error(S.settings.browseFolderUnavailable);
      return;
    }

    try {
      const fallbackPath =
        libraryPath.trim() ||
        await window.electronAPI.getAppPath('documents') ||
        await window.electronAPI.getAppPath('home') ||
        undefined;

      let result;
      try {
        result = await window.electronAPI.openDirectory({
          title: S.settings.browseFolderTitle,
          defaultPath: fallbackPath,
        });
      } catch (error) {
        console.warn('[settings] browse dialog retry without defaultPath:', error);
        result = await window.electronAPI.openDirectory({
          title: S.settings.browseFolderTitle,
        });
      }

      if (!result.canceled && result.directoryPath) {
        setLibraryPath(result.directoryPath);
      }
    } catch (error) {
      console.warn('[settings] browse directory failed:', error);
      toast.error(S.settings.browseFolderFailed);
    }
  }, [libraryPath, toast]);

  const handleDiscard = useCallback(() => {
    clearApiKeyInputs();
    setLibraryPath(baselineSettings.library_path || '');
    setTheme((baselineSettings.theme || 'light') as 'dark' | 'light');
    setAutoAnalyze(baselineSettings.auto_analyze ?? false);
    setPdfParserMode((baselineSettings.pdf_parser_mode || 'java') as 'java');
    setExtractionPipelineVersion((baselineSettings.extraction_pipeline_version || 'resolver_v1') as 'legacy' | 'resolver_v1');
    setResearchContext(baselineSettings.research_context || '');
    setDefaultLevel((baselineSettings.default_explanation_level || 'masters') as LevelKey);
    setSaved(false);
  }, [baselineSettings, clearApiKeyInputs]);

  // -----------------------------------------------------------------------
  // Check for unsaved changes
  // -----------------------------------------------------------------------
  const hasChanges =
    geminiKey.trim() !== '' ||
    libraryPath !== (baselineSettings.library_path || '') ||
    theme !== (baselineSettings.theme || 'light') ||
    autoAnalyze !== (baselineSettings.auto_analyze ?? false) ||
    pdfParserMode !== (baselineSettings.pdf_parser_mode || 'java') ||
    extractionPipelineVersion !== (baselineSettings.extraction_pipeline_version || 'resolver_v1') ||
    researchContext !== (baselineSettings.research_context || '') ||
    defaultLevel !== ((baselineSettings.default_explanation_level || 'masters') as LevelKey);

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
        <div className="page-header-dense gap-4 lg:flex lg:items-start lg:justify-between">
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
                {S.settings.apiKeys} {geminiKeyStatus ? S.settings.statusConfigured : S.settings.statusMissing}
              </span>
              <span className="archive-inline-status archive-inline-status-muted">
                {S.settings.librarySection} {libraryPath ? S.settings.statusConfigured : S.settings.statusMissing}
              </span>
              <span className="archive-inline-status archive-inline-status-muted">
                {S.settings.appearance} {theme === 'light' ? S.settings.light : S.settings.dark}
              </span>
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-stretch gap-2 lg:min-w-[14rem]">
            {(hasChanges || saved) && (
              <div className={saved ? 'archive-inline-status archive-inline-status-success' : 'archive-inline-status archive-inline-status-muted'}>
                {saved ? (
                  <AppIcon name="success" className="w-4 h-4" />
                ) : (
                  <AppIcon name="info" className="w-4 h-4" />
                )}
                {saved ? S.settings.saved : S.settings.unsavedChanges}
              </div>
            )}
            <div className="flex items-center gap-2">
              <button
                onClick={handleDiscard}
                disabled={!hasChanges && !saved}
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
                {saving ? S.settings.saving : S.settings.save}
              </button>
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
                  ref={geminiInputRef}
                  type={showGeminiKey ? 'text' : 'password'}
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  name="sasoo-gemini-api-key"
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  data-bwignore="true"
                  spellCheck={false}
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
          </div>
        </SettingPanel>

        <SettingPanel
          kicker={S.settings.sectionEdit}
          title={S.settings.researcherProfile}
          description={S.settings.researcherProfileDesc}
        >
          <div className="space-y-4">
            <div>
              <label className="settings-label text-xs text-surface-400 block mb-1.5" htmlFor="research-context">
                {S.settings.researchContext}
              </label>
              <input
                id="research-context"
                type="text"
                value={researchContext}
                onChange={(e) => setResearchContext(e.target.value)}
                placeholder={S.settings.researchContextPlaceholder}
                className="input"
              />
              <p className="settings-helper text-2xs text-surface-600 mt-1">
                {S.settings.researchContextHelper}
              </p>
            </div>

            <div>
              <label className="settings-label text-xs text-surface-400 block mb-1.5">
                {S.settings.defaultLevel}
              </label>
              <LevelSlider value={defaultLevel} onChange={setDefaultLevel} />
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
              <div className="flex flex-wrap gap-2">
                <input
                  type="text"
                  value={libraryPath}
                  onChange={(e) => setLibraryPath(e.target.value)}
                  placeholder="/path/to/papers"
                  className="input min-w-0 flex-1"
                />
                <button
                  type="button"
                  onClick={handleBrowseDirectory}
                  className="btn-ghost px-3 shrink-0"
                  title={S.settings.browseFolder}
                >
                  <AppIcon name="folder" className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving || !hasChanges}
                  className="btn-primary shrink-0 text-sm"
                >
                  {saving ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <AppIcon name="save" className="w-4 h-4" />
                  )}
                  {saving ? S.settings.saving : S.settings.save}
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
    </div>
  );
}
