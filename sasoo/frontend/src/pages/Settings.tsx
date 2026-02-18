import { useState, useEffect, useCallback } from 'react';
import {
  Settings as SettingsIcon,
  Key,
  Eye,
  EyeOff,
  FolderOpen,
  Save,
  Loader2,
  Check,
  AlertCircle,
  Sun,
  Moon,
  DollarSign,
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
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [autoAnalyze, setAutoAnalyze] = useState(false);

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
        setTheme(data.theme || 'dark');
        setAutoAnalyze(data.auto_analyze ?? false);
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
  }, [geminiKey, claudeKey, libraryPath, theme, autoAnalyze, toast]);

  // -----------------------------------------------------------------------
  // Check for unsaved changes
  // -----------------------------------------------------------------------
  const hasChanges =
    settings &&
    (geminiKey.trim() !== '' ||
      claudeKey.trim() !== '' ||
      libraryPath !== (settings.library_path || '') ||
      theme !== (settings.theme || 'dark') ||
      autoAnalyze !== (settings.auto_analyze ?? false));

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
    <div className="p-6 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-bold text-surface-100 flex items-center gap-2">
            <SettingsIcon className="w-5 h-5 text-primary-400" />
            {S.settings.title}
          </h1>
          <p className="text-sm text-surface-500 mt-1">
            {S.settings.description}
          </p>
        </div>

        <button
          onClick={handleSave}
          disabled={saving || !hasChanges}
          className="btn-primary"
        >
          {saving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : saved ? (
            <Check className="w-4 h-4 text-emerald-300" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          {saving ? S.settings.saving : saved ? S.settings.saved : S.settings.save}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3 mb-6">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="space-y-8">
        {/* ---------------------------------------------------------------- */}
        {/* API Keys */}
        {/* ---------------------------------------------------------------- */}
        <section>
          <h2 className="text-sm font-semibold text-surface-200 flex items-center gap-2 mb-4">
            <Key className="w-4 h-4 text-primary-400" />
            {S.settings.apiKeys}
          </h2>

          <div className="space-y-4">
            {/* Gemini API key */}
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
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-surface-500 hover:text-surface-300 transition-colors"
                  type="button"
                >
                  {showGeminiKey ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
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

            {/* Claude API key */}
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
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded text-surface-500 hover:text-surface-300 transition-colors"
                  type="button"
                >
                  {showClaudeKey ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
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
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Library Configuration */}
        {/* ---------------------------------------------------------------- */}
        <section>
          <h2 className="text-sm font-semibold text-surface-200 flex items-center gap-2 mb-4">
            <FolderOpen className="w-4 h-4 text-primary-400" />
            {S.settings.librarySection}
          </h2>

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
                  <FolderOpen className="w-4 h-4" />
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
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Appearance */}
        {/* ---------------------------------------------------------------- */}
        <section>
          <h2 className="text-sm font-semibold text-surface-200 flex items-center gap-2 mb-4">
            {theme === 'dark' ? (
              <Moon className="w-4 h-4 text-primary-400" />
            ) : (
              <Sun className="w-4 h-4 text-primary-400" />
            )}
            {S.settings.appearance}
          </h2>

          <div className="flex items-center gap-3">
            <button
              onClick={() => setTheme('dark')}
              className={`flex items-center gap-2 px-4 py-3 rounded-lg border transition-colors ${
                theme === 'dark'
                  ? 'border-primary-500 bg-primary-500/10 text-primary-400'
                  : 'border-surface-700 bg-surface-800 text-surface-400 hover:border-surface-600'
              }`}
            >
              <Moon className="w-4 h-4" />
              <span className="text-sm">{S.settings.dark}</span>
            </button>
            <button
              onClick={() => setTheme('light')}
              className={`flex items-center gap-2 px-4 py-3 rounded-lg border transition-colors ${
                theme === 'light'
                  ? 'border-primary-500 bg-primary-500/10 text-primary-400'
                  : 'border-surface-700 bg-surface-800 text-surface-400 hover:border-surface-600'
              }`}
            >
              <Sun className="w-4 h-4" />
              <span className="text-sm">{S.settings.light}</span>
            </button>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Usage & Cost Dashboard */}
        {/* ---------------------------------------------------------------- */}
        <section>
          <h2 className="text-sm font-semibold text-surface-200 flex items-center gap-2 mb-4">
            <DollarSign className="w-4 h-4 text-primary-400" />
            {S.settings.usageCosts}
          </h2>
          <CostDashboard />
        </section>
      </div>

      {/* Sticky save bar when changes exist */}
      {hasChanges && (
        <div className="fixed bottom-0 left-0 right-0 bg-surface-800/85 backdrop-blur-lg border-t border-surface-700/50 px-6 py-3 z-40">
          <div className="max-w-3xl mx-auto flex items-center justify-between">
            <span className="text-sm text-surface-400">
              {S.settings.unsavedChanges}
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  // Discard: reset to server values
                  setGeminiKey('');
                  setClaudeKey('');
                  if (settings) {
                    setLibraryPath(settings.library_path || '');
                    setTheme(settings.theme || 'dark');
                    setAutoAnalyze(settings.auto_analyze ?? false);
                  }
                }}
                className="btn-ghost text-sm"
              >
                {S.settings.discard}
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="btn-primary text-sm"
              >
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
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
