import { useState, useEffect, useCallback } from 'react';
import {
  getSettings,
  updateSettings,
} from '@/lib/api';
import { type LevelKey } from '@/components/LevelSlider';
import { LevelCards } from '@/components/profile/LevelCards';
import { AreaPicker } from '@/components/profile/AreaPicker';
import { SaveBar } from '@/components/settings/SaveBar';
import { SettingSection, SettingRow, SegmentGroup } from '@/components/settings/SettingPrimitives';
import { useToast } from '@/components/Toast';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import { Select } from '@/components/ui';

// ---------------------------------------------------------------------------
// 연구자 프로필 — 연구 배경과 기본 설명 수준을 관리하는 전용 페이지.
// analysis_focus(분석 초점)는 논문마다 다르므로 여기 두지 않고 업로드 화면에서만 받는다.
// 레이아웃은 Settings.tsx와 같은 원시 컴포넌트(SettingSection/SettingRow/SegmentGroup)를 쓴다.
// ---------------------------------------------------------------------------

// 주요 연구 분야 - 최대 3개. key는 백엔드 research_areas로 그대로 저장된다.
// AreaPicker의 max prop으로 넘긴다 - 상한 값을 두 곳에 따로 박지 않는다.
const MAX_RESEARCH_AREAS = 3;

// 아래 세 표의 key는 backend/api/analysis_context.py의 표와 집합이 같아야 한다
// (test_analysis_context.py가 고정). 라벨은 S.profile이 단일 출처다.
const toOptions = (labels: Record<string, string>) =>
  Object.entries(labels).map(([key, label]) => ({ key, label }));

// 분야 숙련도 — 5단계 세그먼트
const FIELD_EXPERTISE_OPTIONS = toOptions(S.profile.fieldExpertise);
const DEFAULT_FIELD_EXPERTISE = 'major';

// 논문 읽기 경험 — 4단계 세그먼트
const READING_EXPERIENCE_OPTIONS = toOptions(S.profile.readingExperience);
const DEFAULT_READING_EXPERIENCE = 'regular';

// 연구 역할 — 단일 선택 드롭다운
const RESEARCH_ROLE_OPTIONS = toOptions(S.profile.researchRole);
const DEFAULT_RESEARCH_ROLE = 'grad_student';

export default function Profile() {
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [baseline, setBaseline] = useState<{
    research_context: string;
    default_explanation_level: string;
    research_areas: string[];
    field_expertise: string;
    reading_experience: string;
    research_role: string;
  }>({
    research_context: '',
    default_explanation_level: 'masters',
    research_areas: [],
    field_expertise: DEFAULT_FIELD_EXPERTISE,
    reading_experience: DEFAULT_READING_EXPERIENCE,
    research_role: DEFAULT_RESEARCH_ROLE,
  });
  const [researchContext, setResearchContext] = useState('');
  const [defaultLevel, setDefaultLevel] = useState<LevelKey>('masters');
  const [researchAreas, setResearchAreas] = useState<string[]>([]);
  const [fieldExpertise, setFieldExpertise] = useState(DEFAULT_FIELD_EXPERTISE);
  const [readingExperience, setReadingExperience] = useState(DEFAULT_READING_EXPERIENCE);
  const [researchRole, setResearchRole] = useState(DEFAULT_RESEARCH_ROLE);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((data) => {
        if (cancelled) return;
        setResearchContext(data.research_context || '');
        setDefaultLevel((data.default_explanation_level || 'masters') as LevelKey);
        setResearchAreas(data.research_areas || []);
        setFieldExpertise(data.field_expertise || DEFAULT_FIELD_EXPERTISE);
        setReadingExperience(data.reading_experience || DEFAULT_READING_EXPERIENCE);
        setResearchRole(data.research_role || DEFAULT_RESEARCH_ROLE);
        setBaseline({
          research_context: data.research_context || '',
          default_explanation_level: data.default_explanation_level || 'masters',
          research_areas: data.research_areas || [],
          field_expertise: data.field_expertise || DEFAULT_FIELD_EXPERTISE,
          reading_experience: data.reading_experience || DEFAULT_READING_EXPERIENCE,
          research_role: data.research_role || DEFAULT_RESEARCH_ROLE,
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

  // 저장바가 "변경 N개"를 보여주므로 불리언이 아니라 개수를 센다. Settings.tsx와 같은 형태다.
  const changedFields = [
    researchContext !== baseline.research_context,
    JSON.stringify(researchAreas) !== JSON.stringify(baseline.research_areas),
    researchRole !== baseline.research_role,
    defaultLevel !== baseline.default_explanation_level,
    fieldExpertise !== baseline.field_expertise,
    readingExperience !== baseline.reading_experience,
  ].filter(Boolean).length;

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateSettings({
        research_context: researchContext,
        default_explanation_level: defaultLevel,
        research_areas: researchAreas,
        field_expertise: fieldExpertise,
        reading_experience: readingExperience,
        research_role: researchRole,
      });
      setResearchContext(updated.research_context || '');
      setDefaultLevel((updated.default_explanation_level || 'masters') as LevelKey);
      setResearchAreas(updated.research_areas || []);
      setFieldExpertise(updated.field_expertise || DEFAULT_FIELD_EXPERTISE);
      setReadingExperience(updated.reading_experience || DEFAULT_READING_EXPERIENCE);
      setResearchRole(updated.research_role || DEFAULT_RESEARCH_ROLE);
      setBaseline({
        research_context: updated.research_context || '',
        default_explanation_level: updated.default_explanation_level || 'masters',
        research_areas: updated.research_areas || [],
        field_expertise: updated.field_expertise || DEFAULT_FIELD_EXPERTISE,
        reading_experience: updated.reading_experience || DEFAULT_READING_EXPERIENCE,
        research_role: updated.research_role || DEFAULT_RESEARCH_ROLE,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
      // 성공 피드백은 SaveBar가 사라지는 것 자체다 - 토스트를 겹치지 않는다(SaveBar.tsx 참고).
    } catch (err) {
      setError(err instanceof Error ? err.message : S.settings.saveFailed);
      if (err instanceof Error) console.warn('[profile] save error:', err.message);
      toast.error(S.toast.settingsFailed);
    } finally {
      setSaving(false);
    }
  }, [researchContext, defaultLevel, researchAreas, fieldExpertise, readingExperience, researchRole, toast]);

  const handleDiscard = useCallback(() => {
    setResearchContext(baseline.research_context);
    setDefaultLevel(baseline.default_explanation_level as LevelKey);
    setResearchAreas(baseline.research_areas);
    setFieldExpertise(baseline.field_expertise);
    setReadingExperience(baseline.reading_experience);
    setResearchRole(baseline.research_role);
    setSaved(false);
  }, [baseline]);

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
            <div className="archive-kicker">{S.profile.heroKicker}</div>
            <h1 className="settings-hero-title mt-2 text-[1.8rem] font-semibold tracking-tighter">
              {S.settings.researcherProfile}
            </h1>
            <p className="settings-hero-body mt-2 text-sm leading-6">
              {S.settings.researcherProfileDesc} {S.profile.defaultsNote}
            </p>
          </div>
          {/* 저장·되돌리기 버튼은 하단 저장바(SaveBar)로 옮겼다. */}
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

      <div className="space-y-4">
        {/* 1. 연구 배경 — 내가 어떤 분야에서 무엇을 연구하는지 */}
        <SettingSection title={S.profile.backgroundTitle} description={S.profile.backgroundDesc}>
          <SettingRow full label={S.settings.researchContext} description={S.settings.researchContextHelper}>
            <textarea
              value={researchContext}
              onChange={(e) => setResearchContext(e.target.value)}
              placeholder={S.settings.researchContextPlaceholder}
              aria-label={S.settings.researchContext}
              rows={3}
              className="input resize-none"
            />
          </SettingRow>

          <SettingRow full label={S.settings.researchAreas}>
            <AreaPicker value={researchAreas} onChange={setResearchAreas} max={MAX_RESEARCH_AREAS} />
          </SettingRow>

          <SettingRow label={S.settings.researchRole}>
            <div className="w-56">
              <Select
                value={researchRole}
                onValueChange={setResearchRole}
                options={RESEARCH_ROLE_OPTIONS.map((opt) => ({ value: opt.key, label: opt.label }))}
                placeholder={S.settings.researchRolePlaceholder}
                aria-label={S.settings.researchRole}
              />
            </div>
          </SettingRow>
        </SettingSection>

        {/* 2. 설명 눈높이 — 분석이 나에게 설명하는 깊이와 관점 */}
        <SettingSection title={S.profile.levelTitle} description={S.profile.levelDesc}>
          <SettingRow full label={S.settings.defaultLevel}>
            <LevelCards value={defaultLevel} onChange={setDefaultLevel} />
          </SettingRow>

          <SettingRow full label={S.settings.fieldExpertise}>
            <SegmentGroup
              options={FIELD_EXPERTISE_OPTIONS}
              value={fieldExpertise}
              onChange={setFieldExpertise}
              ariaLabel={S.settings.fieldExpertise}
            />
          </SettingRow>

          <SettingRow full label={S.settings.readingExperience}>
            <SegmentGroup
              options={READING_EXPERIENCE_OPTIONS}
              value={readingExperience}
              onChange={setReadingExperience}
              ariaLabel={S.settings.readingExperience}
            />
          </SettingRow>
        </SettingSection>
      </div>

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
