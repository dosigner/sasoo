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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Settings() {
  const [settings, setSettings] = useState<SettingsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form state
  const [geminiKey, setGeminiKey] = useState('');
  const [claudeKey, setClaudeKey] = useState('');
  const [libraryPath, setLibraryPath] = useState('');
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [autoAnalyze, setAutoAnalyze] = useState(false);
  const [monthlyBudget, setMonthlyBudget] = useState(50);

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
        setGeminiKey(data.gemini_api_key || '');
        setClaudeKey(data.anthropic_api_key || '');
        setLibraryPath(data.library_path || '');
        setTheme(data.theme || 'dark');
        setAutoAnalyze(data.auto_analyze ?? false);
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : 'Failed to load settings'
          );
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
    // Sync to localStorage so App.tsx can restore on next load
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
      const updated = await updateSettings({
        gemini_api_key: geminiKey,
        anthropic_api_key: claudeKey,
        library_path: libraryPath,
        theme,
        auto_analyze: autoAnalyze,
      });
      setSettings(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to save settings'
      );
    } finally {
      setSaving(false);
    }
  }, [geminiKey, claudeKey, libraryPath, theme, autoAnalyze]);

  // -----------------------------------------------------------------------
  // Check for unsaved changes
  // -----------------------------------------------------------------------
  const hasChanges =
    settings &&
    (geminiKey !== (settings.gemini_api_key || '') ||
      claudeKey !== (settings.anthropic_api_key || '') ||
      libraryPath !== (settings.library_path || '') ||
      theme !== (settings.theme || 'dark') ||
      autoAnalyze !== (settings.auto_analyze ?? false));

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 text-primary-400 animate-spin" />
          <span className="text-sm text-surface-400">Loading settings...</span>
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
            Settings
          </h1>
          <p className="text-sm text-surface-500 mt-1">
            Configure API keys, preferences, and view usage statistics.
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
          {saving ? 'Saving...' : saved ? 'Saved' : 'Save Changes'}
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
            API Keys
          </h2>

          <div className="space-y-4">
            {/* Gemini API key */}
            <div>
              <label className="text-xs text-surface-400 block mb-1.5">
                Google Gemini API Key
              </label>
              <div className="relative">
                <input
                  type={showGeminiKey ? 'text' : 'password'}
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  placeholder="AIza..."
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
                Used for Gemini Flash and Gemini Pro models. Get a key at{' '}
                <a
                  href="https://aistudio.google.com/api-keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary-400 hover:text-primary-300 underline underline-offset-2"
                >
                  Google AI Studio
                </a>
                .
              </p>
            </div>

            {/* Claude API key */}
            <div>
              <label className="text-xs text-surface-400 block mb-1.5">
                Anthropic Claude API Key
              </label>
              <div className="relative">
                <input
                  type={showClaudeKey ? 'text' : 'password'}
                  value={claudeKey}
                  onChange={(e) => setClaudeKey(e.target.value)}
                  placeholder="sk-ant-..."
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
                Used for Claude Sonnet for advanced analysis. Get a key at{' '}
                <a
                  href="https://platform.claude.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary-400 hover:text-primary-300 underline underline-offset-2"
                >
                  Anthropic Console
                </a>
                .
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
            Library
          </h2>

          <div className="space-y-4">
            <div>
              <label className="text-xs text-surface-400 block mb-1.5">
                Library Storage Path
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
                        title: 'Select Library Folder',
                        defaultPath: libraryPath || undefined,
                      });
                      if (!result.canceled && result.directoryPath) {
                        setLibraryPath(result.directoryPath);
                      }
                    }
                  }}
                  className="btn-ghost px-3 shrink-0"
                  title="Browse folder"
                >
                  <FolderOpen className="w-4 h-4" />
                </button>
              </div>
              <p className="text-2xs text-surface-600 mt-1">
                Directory where uploaded PDFs and analysis results are stored.
                Changes take effect after restarting the app. Existing files are not moved automatically.
              </p>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <label className="text-xs text-surface-300">
                  Auto-analyze on upload
                </label>
                <p className="text-2xs text-surface-600 mt-0.5">
                  Automatically start analysis when a paper is uploaded.
                </p>
              </div>
              <button
                onClick={() => setAutoAnalyze(!autoAnalyze)}
                className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
                  autoAnalyze ? 'bg-primary-500' : 'bg-surface-600'
                }`}
                type="button"
                role="switch"
                aria-checked={autoAnalyze}
              >
                <span
                  className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                    autoAnalyze ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
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
            Appearance
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
              <span className="text-sm">Dark</span>
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
              <span className="text-sm">Light</span>
            </button>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Budget */}
        {/* ---------------------------------------------------------------- */}
        <section>
          <h2 className="text-sm font-semibold text-surface-200 flex items-center gap-2 mb-4">
            <DollarSign className="w-4 h-4 text-primary-400" />
            Budget
          </h2>

          <div>
            <label className="text-xs text-surface-400 block mb-1.5">
              Monthly Budget Limit
            </label>
            <div className="relative w-40">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-surface-500">
                $
              </span>
              <input
                type="number"
                min={0}
                step={5}
                value={monthlyBudget}
                onChange={(e) =>
                  setMonthlyBudget(parseFloat(e.target.value) || 0)
                }
                className="input pl-7"
              />
            </div>
            <p className="text-2xs text-surface-600 mt-1">
              You'll receive warnings when approaching this limit.
            </p>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* Cost Dashboard */}
        {/* ---------------------------------------------------------------- */}
        <section>
          <h2 className="text-sm font-semibold text-surface-200 flex items-center gap-2 mb-4">
            <DollarSign className="w-4 h-4 text-primary-400" />
            Usage & Costs
          </h2>
          <CostDashboard />
        </section>
      </div>

      {/* Sticky save bar when changes exist */}
      {hasChanges && (
        <div className="fixed bottom-0 left-0 right-0 bg-surface-800/85 backdrop-blur-lg border-t border-surface-700/50 px-6 py-3 z-40">
          <div className="max-w-3xl mx-auto flex items-center justify-between">
            <span className="text-sm text-surface-400">
              You have unsaved changes
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (settings) {
                    setGeminiKey(settings.gemini_api_key || '');
                    setClaudeKey(settings.anthropic_api_key || '');
                    setLibraryPath(settings.library_path || '');
                    setTheme(settings.theme || 'dark');
                    setAutoAnalyze(settings.auto_analyze ?? false);
                  }
                }}
                className="btn-ghost text-sm"
              >
                Discard
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
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
