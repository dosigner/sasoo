import { useState, useEffect, useCallback } from 'react';
import { Loader2 } from 'lucide-react';
import {
  getSettings,
  updateSettings,
} from '@/lib/api';
import LevelSlider, { type LevelKey } from '@/components/LevelSlider';
import { useToast } from '@/components/Toast';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';

// ---------------------------------------------------------------------------
// 연구자 프로필 — 연구 배경과 기본 설명 수준을 관리하는 전용 페이지.
// analysis_focus(분석 초점)는 논문마다 다르므로 여기 두지 않고 업로드 화면에서만 받는다.
// ---------------------------------------------------------------------------

export default function Profile() {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [baseline, setBaseline] = useState<{ research_context: string; default_explanation_level: string }>({
    research_context: '',
    default_explanation_level: 'masters',
  });
  const [researchContext, setResearchContext] = useState('');
  const [defaultLevel, setDefaultLevel] = useState<LevelKey>('masters');

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((data) => {
        if (cancelled) return;
        setResearchContext(data.research_context || '');
        setDefaultLevel((data.default_explanation_level || 'masters') as LevelKey);
        setBaseline({
          research_context: data.research_context || '',
          default_explanation_level: data.default_explanation_level || 'masters',
        });
      })
      .catch((err) => {
        if (!cancelled) {
          if (err instanceof Error) console.warn('[profile] load error:', err.message);
          setError(S.settings.loadFailed);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const hasChanges =
    researchContext !== baseline.research_context ||
    defaultLevel !== baseline.default_explanation_level;

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateSettings({
        research_context: researchContext,
        default_explanation_level: defaultLevel,
      });
      setResearchContext(updated.research_context || '');
      setDefaultLevel((updated.default_explanation_level || 'masters') as LevelKey);
      setBaseline({
        research_context: updated.research_context || '',
        default_explanation_level: updated.default_explanation_level || 'masters',
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      toast.success(S.toast.settingsSaved);
    } catch (err) {
      setError(err instanceof Error ? err.message : S.settings.saveFailed);
      if (err instanceof Error) console.warn('[profile] save error:', err.message);
      toast.error(S.toast.settingsFailed);
    } finally {
      setSaving(false);
    }
  }, [researchContext, defaultLevel, toast]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 text-accent animate-spin" />
          <span className="text-sm text-fg-muted">{S.settings.loadingSettings}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container-compact">
      <section className="archive-panel panel-compact mb-4">
        <div className="page-header-dense gap-4 lg:flex lg:items-start lg:justify-between">
          <div>
            <div className="archive-kicker">{S.profile.heroKicker}</div>
            <h1 className="settings-hero-title mt-2 text-[1.8rem] font-semibold tracking-[-0.05em]">
              {S.settings.researcherProfile}
            </h1>
            <p className="settings-hero-body mt-2 text-sm leading-6">
              {S.settings.researcherProfileDesc}
            </p>
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
      </section>

      {error && (
        <div className="mb-4 archive-inline-status archive-inline-status-error">
          <AppIcon name="warning" className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <section className="archive-panel panel-compact">
        <div className="mb-4">
          <div className="archive-kicker">{S.settings.sectionEdit}</div>
          <h2 className="settings-panel-title mt-2 text-xl font-semibold tracking-[-0.04em]">
            {S.profile.sectionTitle}
          </h2>
          <p className="settings-panel-description mt-2 max-w-2xl text-sm leading-6">
            {S.profile.sectionDesc}
          </p>
        </div>

        <div className="space-y-5">
          <div>
            <label htmlFor="research-context" className="text-xs text-fg-muted block mb-1.5">
              {S.settings.researchContext}
            </label>
            <textarea
              id="research-context"
              value={researchContext}
              onChange={(e) => setResearchContext(e.target.value)}
              placeholder={S.settings.researchContextPlaceholder}
              rows={3}
              className="input resize-none"
            />
            <p className="text-2xs text-fg-muted mt-1">
              {S.settings.researchContextHelper}
            </p>
          </div>

          <div>
            <label className="text-xs text-fg-muted block mb-1.5">
              {S.settings.defaultLevel}
            </label>
            <LevelSlider value={defaultLevel} onChange={setDefaultLevel} />
          </div>
        </div>
      </section>
    </div>
  );
}
