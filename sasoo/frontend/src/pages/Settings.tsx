import { useState, useEffect, useCallback, useRef } from 'react';
import { useLocation, Link } from 'react-router';
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
import { ProviderCards, type Provider } from '@/components/settings/ProviderCards';
import { SaveBar } from '@/components/settings/SaveBar';
import { Select, Toggle } from '@/components/ui';
import { S } from '@/lib/strings';
import { applyTheme, readStoredTheme, type Theme } from '@/lib/theme';
import { AppIcon } from '@/components/icons';

// ---------------------------------------------------------------------------
// L1 layout primitives — narrow single column, row-based settings.
// ---------------------------------------------------------------------------

function SettingSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="archive-panel panel-compact">
      <h2 className="text-sm font-semibold tracking-apple-body text-fg">{title}</h2>
      {description && (
        <p className="mt-1 text-xs text-fg-muted">{description}</p>
      )}
      <div className="mt-3 flex flex-col gap-1">{children}</div>
    </section>
  );
}

function SettingRow({
  label,
  description,
  badge,
  full = false,
  children,
}: {
  label: string;
  description?: React.ReactNode;
  badge?: React.ReactNode;
  full?: boolean;
  children: React.ReactNode;
}) {
  if (full) {
    return (
      <div className="settings-row-block">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-fg">{label}</span>
          {badge}
        </div>
        {description && (
          <p className="mt-0.5 text-xs text-fg-muted">{description}</p>
        )}
        <div className="mt-2">{children}</div>
      </div>
    );
  }
  return (
    <div className="settings-row-block flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-fg">{label}</span>
          {badge}
        </div>
        {description && (
          <p className="mt-0.5 text-xs text-fg-muted">{description}</p>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const defaultSettings: SettingsType = {
    gemini_api_key: '',
    gemini_key_unreadable: false,
    openai_api_key: '',
    openai_key_unreadable: false,
    image_provider: 'openai',
    image_quality: 'high',
    library_path: '',
    default_domain: 'optics',
    auto_analyze: false,
    language: 'ko',
    theme: 'light',
    max_concurrent_analyses: 3,
    pdf_parser_mode: 'java',
    extraction_pipeline_version: 'resolver_v1',
    pdf_visual_engine: 'gemini',
    research_context: '',
    default_explanation_level: 'masters',
    research_areas: [],
    field_expertise: 'major',
    reading_experience: 'regular',
    research_role: 'grad_student',
  };

  const [baselineSettings, setBaselineSettings] = useState<SettingsType>(defaultSettings);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast } = useToast();
  const location = useLocation();
  const costSectionRef = useRef<HTMLDivElement | null>(null);

  // Form state
  const [geminiKey, setGeminiKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [libraryPath, setLibraryPath] = useState('');
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme() ?? 'light');
  const [autoAnalyze, setAutoAnalyze] = useState(false);
  const [pdfParserMode, setPdfParserMode] = useState<'java'>('java');
  const [extractionPipelineVersion, setExtractionPipelineVersion] = useState<'resolver_v1'>('resolver_v1');
  const [pdfVisualEngine, setPdfVisualEngine] = useState<'gemini' | 'odl'>('gemini');
  const [imageQuality, setImageQuality] = useState<'low' | 'medium' | 'high'>('high');
  const [aiProvider, setAiProvider] = useState<Provider>('openai');

  // API key status (masked value from server, for display only)
  const [geminiKeyStatus, setGeminiKeyStatus] = useState('');
  const [geminiKeyUnreadable, setGeminiKeyUnreadable] = useState(false);
  const [openaiKeyStatus, setOpenaiKeyStatus] = useState('');
  const [openaiKeyUnreadable, setOpenaiKeyUnreadable] = useState(false);

  // Visibility toggles
  const [showGeminiKey, setShowGeminiKey] = useState(false);
  const [showOpenaiKey, setShowOpenaiKey] = useState(false);
  const geminiInputRef = useRef<HTMLInputElement | null>(null);
  const openaiInputRef = useRef<HTMLInputElement | null>(null);

  const clearApiKeyInputs = useCallback(() => {
    setGeminiKey('');
    if (geminiInputRef.current) geminiInputRef.current.value = '';
    setOpenaiKey('');
    if (openaiInputRef.current) openaiInputRef.current.value = '';
  }, []);

  const applySettingsToForm = useCallback((data: SettingsType) => {
    setLibraryPath(data.library_path || '');
    // Theme is already initialized from localStorage (the live, instantly-applied
    // preference) and kept in sync by the effect below. Only fall back to the
    // backend value on a true first run, where no local preference exists yet —
    // otherwise a stale/unsaved backend value would silently revert an
    // already-applied theme toggle on every settings reload.
    if (!readStoredTheme() && data.theme) {
      setTheme(data.theme as Theme);
    }
    setAutoAnalyze(data.auto_analyze ?? false);
    setPdfParserMode((data.pdf_parser_mode || 'java') as 'java');
    setExtractionPipelineVersion(
      (data.extraction_pipeline_version || 'resolver_v1') as 'resolver_v1'
    );
    setPdfVisualEngine((data.pdf_visual_engine || 'gemini') as 'gemini' | 'odl');
    setAiProvider((data.ai_provider || 'openai') as Provider);
    setImageQuality((data.image_quality || 'high') as 'low' | 'medium' | 'high');
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
        setGeminiKeyUnreadable(data.gemini_key_unreadable ?? false);
        setOpenaiKeyStatus(data.openai_api_key || '');
        setOpenaiKeyUnreadable(data.openai_key_unreadable ?? false);
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
    applyTheme(theme);
  }, [theme]);

  // -----------------------------------------------------------------------
  // Deep-link into the cost section (Home "자세히 보기" -> /settings#cost)
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (loading) return;
    if (location.hash === '#cost' && costSectionRef.current) {
      costSectionRef.current.scrollIntoView({ block: 'start' });
    }
  }, [loading, location.hash]);

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
        pdf_visual_engine: pdfVisualEngine,
        // image_provider는 보내지 않는다 — 백엔드가 ai_provider의 미러로
        // 함께 갱신한다(services/provider_state.mirror_legacy_settings).
        ai_provider: aiProvider,
        image_quality: imageQuality,
      };
      if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
      if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();

      const updated = await updateSettings(payload);
      setBaselineSettings(updated);
      applySettingsToForm(updated);
      // Update status badges with new masked values
      setGeminiKeyStatus(updated.gemini_api_key || '');
      setGeminiKeyUnreadable(updated.gemini_key_unreadable ?? false);
      setOpenaiKeyStatus(updated.openai_api_key || '');
      setOpenaiKeyUnreadable(updated.openai_key_unreadable ?? false);
      // Clear key inputs after save. This also fights password-manager autofill
      // that can leave the settings screen permanently "dirty".
      clearApiKeyInputs();
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      // 성공 피드백은 저장바가 사라지는 것 자체다 — 토스트를 겹치지 않는다.
      // 다만 키가 사라져 공급사가 자동 전환된 것은 사용자가 요청하지 않은
      // 변화이므로 알린다.
      if (updated.switched_to) {
        const label =
          updated.switched_to === 'openai'
            ? S.settings.aiProviderOpenAI
            : S.settings.aiProviderGemini;
        toast.info(S.settings.aiProviderSwitched(label));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : S.settings.saveFailed);
      if (err instanceof Error) console.warn('[settings] save error:', err.message);
      toast.error(S.toast.settingsFailed);
    } finally {
      setSaving(false);
    }
  }, [geminiKey, openaiKey, libraryPath, theme, autoAnalyze, pdfParserMode, extractionPipelineVersion, pdfVisualEngine, aiProvider, imageQuality, toast, applySettingsToForm, clearApiKeyInputs]);

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
    setExtractionPipelineVersion((baselineSettings.extraction_pipeline_version || 'resolver_v1') as 'resolver_v1');
    setPdfVisualEngine((baselineSettings.pdf_visual_engine || 'gemini') as 'gemini' | 'odl');
    setAiProvider((baselineSettings.ai_provider || 'openai') as Provider);
    setImageQuality((baselineSettings.image_quality || 'high') as 'low' | 'medium' | 'high');
    setSaved(false);
  }, [baselineSettings, clearApiKeyInputs]);

  // -----------------------------------------------------------------------
  // Check for unsaved changes
  // -----------------------------------------------------------------------
  // 저장바가 "변경 N개"를 보여주므로 불리언이 아니라 개수를 센다. 사용자가
  // 무심코 건드린 게 있는지 확인하고 되돌리기를 누를지 판단하는 근거가 된다.
  //
  // image_provider는 세지 않는다 — ai_provider의 미러라 백엔드가 함께 갱신한다.
  const changedFields = [
    geminiKey.trim() !== '',
    openaiKey.trim() !== '',
    aiProvider !== (baselineSettings.ai_provider || 'openai'),
    libraryPath !== (baselineSettings.library_path || ''),
    theme !== (baselineSettings.theme || 'light'),
    autoAnalyze !== (baselineSettings.auto_analyze ?? false),
    pdfVisualEngine !== (baselineSettings.pdf_visual_engine || 'gemini'),
    imageQuality !== (baselineSettings.image_quality || 'high'),
  ].filter(Boolean).length;

  const hasChanges = changedFields > 0;

  // 공급사 카드의 키 상태는 저장된 값 기준이다. 타이핑 중인 입력으로 판정하면
  // 글자를 칠 때마다 카드가 깜빡인다.
  const hasSavedOpenAIKey = Boolean(baselineSettings.openai_api_key);
  const hasSavedGeminiKey = Boolean(baselineSettings.gemini_api_key);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-sm shimmer-label">{S.settings.loadingSettings}</span>
      </div>
    );
  }

  return (
    <div className="page-container-settings">
      <section className="archive-panel panel-compact mb-4">
        <div className="page-header-dense gap-4 lg:flex lg:items-start lg:justify-between">
          <div>
            <div className="archive-kicker">{S.settings.heroKicker}</div>
            <h1 className="settings-hero-title mt-2 text-[1.8rem] font-semibold tracking-tighter">
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
          {/* 저장·되돌리기 버튼은 하단 저장바(SaveBar)로 옮겼다. 페이지가 길어
              헤더에 두면 아래쪽을 편집하는 동안 화면 밖으로 사라진다. */}
          {saved && (
            <div className="archive-inline-status archive-inline-status-success shrink-0">
              <AppIcon name="success" className="w-4 h-4" />
              {S.settings.saved}
            </div>
          )}
        </div>
      </section>

      {error && (
        <div className="mb-4 archive-inline-status archive-inline-status-error">
          <AppIcon name="warning" className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <Link
        to="/profile"
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-accent transition-colors hover:text-accent-hover"
      >
        <AppIcon name="agents" className="w-4 h-4" />
        {S.settings.openProfileLink}
        <AppIcon name="arrow-right" className="w-3.5 h-3.5" />
      </Link>

      <div className="space-y-4">
        {/* 1. AI 공급사 — 이 페이지의 최상위 결정. 공급사 카드 + 두 키를
            한자리에 모은다. 이전에는 OpenAI 키가 "이미지 생성" 섹션에 있어
            Gemini 키와 따로 놀았다. */}
        <SettingSection
          title={S.settings.aiProvider}
          description={S.settings.aiProviderDesc}
        >
          <div className="py-3">
            <ProviderCards
              value={aiProvider}
              onChange={setAiProvider}
              hasOpenAIKey={hasSavedOpenAIKey}
              hasGeminiKey={hasSavedGeminiKey}
            />
            {!hasSavedOpenAIKey && !hasSavedGeminiKey && (
              <p className="mt-2 text-xs text-fg-muted">{S.settings.aiProviderLocked}</p>
            )}
          </div>
          <SettingRow
            full
            label={S.settings.openaiKey}
            badge={
              openaiKeyStatus ? (
                <span className="text-2xs text-success bg-success/10 border border-success/20 px-1.5 py-0.5 rounded-sm">
                  {S.settings.keyConfigured} ({openaiKeyStatus})
                </span>
              ) : openaiKeyUnreadable ? (
                <span className="text-2xs text-danger bg-danger/10 border border-danger/20 px-1.5 py-0.5 rounded-sm">
                  {S.settings.keyUnreadable}
                </span>
              ) : (
                <span className="text-2xs text-warning bg-warning/10 border border-warning/20 px-1.5 py-0.5 rounded-sm">
                  {S.settings.keyNotConfigured}
                </span>
              )
            }
          >
            {openaiKeyUnreadable && (
              <p className="text-2xs text-danger mb-1.5">
                {S.settings.keyUnreadableHelp}
              </p>
            )}
            <div className="relative">
              <input
                ref={openaiInputRef}
                type={showOpenaiKey ? 'text' : 'password'}
                value={openaiKey}
                onChange={(e) => setOpenaiKey(e.target.value)}
                name="sasoo-openai-api-key"
                autoComplete="off"
                data-lpignore="true"
                data-1p-ignore="true"
                data-bwignore="true"
                spellCheck={false}
                placeholder={S.settings.enterNewKey}
                className="input pr-10"
              />
              <button
                onClick={() => setShowOpenaiKey(!showOpenaiKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-fg-muted hover:text-fg-secondary transition-colors"
                style={{ borderRadius: 'var(--radius-control)' }}
                type="button"
              >
                {showOpenaiKey ? (
                  <AppIcon name="eye-off" className="w-4 h-4" />
                ) : (
                  <AppIcon name="eye" className="w-4 h-4" />
                )}
              </button>
            </div>
            <p className="text-2xs text-fg-muted mt-1">
              {S.settings.openaiHelp}{' '}
              <a
                href="https://platform.openai.com/api-keys"
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:text-accent-hover underline underline-offset-2"
              >
                OpenAI Platform
              </a>
              {S.settings.getKeyAt('')}
            </p>
          </SettingRow>

          <SettingRow
            full
            label={S.settings.geminiKey}
            badge={
              geminiKeyStatus ? (
                <span className="text-2xs text-success bg-success/10 border border-success/20 px-1.5 py-0.5 rounded-sm">
                  {S.settings.keyConfigured} ({geminiKeyStatus})
                </span>
              ) : geminiKeyUnreadable ? (
                <span className="text-2xs text-danger bg-danger/10 border border-danger/20 px-1.5 py-0.5 rounded-sm">
                  {S.settings.keyUnreadable}
                </span>
              ) : (
                <span className="text-2xs text-warning bg-warning/10 border border-warning/20 px-1.5 py-0.5 rounded-sm">
                  {S.settings.keyNotConfigured}
                </span>
              )
            }
          >
            {geminiKeyUnreadable && (
              <p className="text-2xs text-danger mb-1.5">
                {S.settings.keyUnreadableHelp}
              </p>
            )}
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
                className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-fg-muted hover:text-fg-secondary transition-colors"
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
            <p className="text-2xs text-fg-muted mt-1">
              {S.settings.geminiHelp}{' '}
              <a
                href="https://aistudio.google.com/api-keys"
                target="_blank"
                rel="noopener noreferrer"
                className="text-accent hover:text-accent-hover underline underline-offset-2"
              >
                Google AI Studio
              </a>
              {S.settings.getKeyAt('')}
            </p>
          </SettingRow>
        </SettingSection>

        {/* 2. 분석 */}
        <SettingSection
          title={S.settings.imageSection}
          description={S.settings.imageSectionDesc}
        >
          <SettingRow label={S.settings.pdfVisualEngine} description={S.settings.pdfVisualEngineHelp}>
            <div className="w-56">
              <Select
                value={pdfVisualEngine}
                onValueChange={(value) => setPdfVisualEngine(value as 'gemini' | 'odl')}
                aria-label={S.settings.pdfVisualEngine}
                options={[
                  { value: 'gemini', label: S.settings.pdfVisualEngineGemini },
                  { value: 'odl', label: S.settings.pdfVisualEngineOdl },
                ]}
              />
            </div>
          </SettingRow>

          <SettingRow label={S.settings.imageQuality}>
            <div className="w-44">
              <Select
                value={imageQuality}
                onValueChange={(value) => setImageQuality(value as 'low' | 'medium' | 'high')}
                aria-label={S.settings.imageQuality}
                options={[
                  { value: 'high', label: 'high ($0.17/장)' },
                  { value: 'medium', label: 'medium ($0.04/장)' },
                  { value: 'low', label: 'low ($0.005/장)' },
                ]}
              />
            </div>
          </SettingRow>

          <SettingRow label={S.settings.autoAnalyze} description={S.settings.autoAnalyzeHelp}>
            <Toggle checked={autoAnalyze} onChange={setAutoAnalyze} ariaLabel={S.settings.autoAnalyze} />
          </SettingRow>
        </SettingSection>

        {/* 3. 보관함 */}
        <SettingSection
          title={S.settings.librarySection}
          description="논문이 쌓이는 경로를 정해요."
        >
          <SettingRow full label={S.settings.libraryPath}>
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
            <p className="text-2xs text-fg-muted mt-1">
              {S.settings.libraryPathHelp}
            </p>
          </SettingRow>
        </SettingSection>

        {/* 4. 화면 */}
        <SettingSection title={S.settings.appearance} description="현재 작업 환경에 맞게 화면 톤을 조정해요.">
          <div className="flex items-center gap-3 py-3">
            <button
              onClick={() => setTheme('dark')}
              className={`settings-appearance-option flex items-center gap-2 px-4 py-3 border transition-colors ${
                theme === 'dark'
                  ? 'settings-appearance-option-active border-accent bg-accent/10 text-accent'
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
                  ? 'settings-appearance-option-active border-accent bg-accent/10 text-accent'
                  : 'settings-appearance-option-inactive'
              }`}
              style={{ borderRadius: 'var(--radius-control)' }}
            >
              <AppIcon name="sun" className="w-4 h-4" />
              <span className="text-sm">{S.settings.light}</span>
            </button>
          </div>
        </SettingSection>

        {/* 5. 사용량과 비용 */}
        <div id="cost" ref={costSectionRef}>
          <SettingSection
            title={S.settings.usageCosts}
            description="최근 분석이 얼마나 호출과 비용을 만들었는지 확인해요."
          >
            <CostDashboard />
          </SettingSection>
        </div>
      </div>

      {/* 변경이 있을 때만 나타난다. sticky라 스크롤 컨테이너(.page-scaffold)
          안 44rem 컬럼에 붙어 사이드바 폭을 알 필요가 없다. */}
      <SaveBar
        changeCount={changedFields}
        saving={saving}
        error={error}
        onSave={handleSave}
        onDiscard={handleDiscard}
      />
    </div>
  );
}
