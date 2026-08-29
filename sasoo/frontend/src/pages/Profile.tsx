import { useState, useEffect, useCallback } from 'react';
import {
  getSettings,
  updateSettings,
} from '@/lib/api';
import { type LevelKey } from '@/components/LevelSlider';
import { LevelCards } from '@/components/profile/LevelCards';
import { AreaPicker } from '@/components/profile/AreaPicker';
import { SaveBar } from '@/components/settings/SaveBar';
import { useToast } from '@/components/Toast';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import { Select } from '@/components/ui';

// ---------------------------------------------------------------------------
// 연구자 프로필 — 연구 배경과 기본 설명 수준을 관리하는 전용 페이지.
// analysis_focus(분석 초점)는 논문마다 다르므로 여기 두지 않고 업로드 화면에서만 받는다.
// ---------------------------------------------------------------------------

// 주요 연구 분야 - 최대 3개. key는 백엔드 research_areas로 그대로 저장된다.
// AreaPicker의 max prop으로 넘긴다 - 상한 값을 두 곳에 따로 박지 않는다.
const MAX_RESEARCH_AREAS = 3;

// 분야 숙련도 — 5단계 세그먼트
const FIELD_EXPERTISE_OPTIONS = [
  { key: 'novice', label: '입문' },
  { key: 'basic', label: '기초 이해' },
  { key: 'major', label: '전공 수준' },
  { key: 'research', label: '연구 수행' },
  { key: 'expert', label: '전문가' },
] as const;
const DEFAULT_FIELD_EXPERTISE = 'major';

// 논문 읽기 경험 — 4단계 세그먼트
const READING_EXPERIENCE_OPTIONS = [
  { key: 'rare', label: '거의 없음' },
  { key: 'occasional', label: '가끔 읽음' },
  { key: 'regular', label: '정기적으로 읽음' },
  { key: 'author', label: '작성·심사 경험' },
] as const;
const DEFAULT_READING_EXPERIENCE = 'regular';

// 연구 역할 — 단일 선택 드롭다운
const RESEARCH_ROLE_OPTIONS = [
  { key: 'student', label: '학생 연구자' },
  { key: 'grad_student', label: '대학원생' },
  { key: 'postdoc', label: '연구원·박사후연구원' },
  { key: 'professor', label: '교수·PI' },
  { key: 'engineer', label: '엔지니어' },
  { key: 'manager', label: '연구 관리자' },
  { key: 'other', label: '기타' },
] as const;
const DEFAULT_RESEARCH_ROLE = 'grad_student';

// 5/4단계 세그먼트 컨트롤 — iOS식 인셋 트랙. 선택된 세그먼트가 트랙 위로
// 살짝 떠오른 pill(surface + shadow)로 보이고, 누를 때 미세하게 눌린다(reduced-motion 존중).
function SegmentGroup({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: readonly { key: string; label: string }[];
  value: string;
  onChange: (key: string) => void;
  ariaLabel: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="inline-flex max-w-full flex-wrap gap-1 rounded-control border border-border/50 bg-bg/60 p-1"
    >
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={opt.key}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(opt.key)}
            className={`rounded-control px-3.5 py-2 text-sm transition-all duration-150 ease-out motion-safe:active:scale-[0.97] ${
              active
                ? 'bg-surface font-medium text-fg shadow-sm'
                : 'text-fg-muted hover:text-fg-secondary'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

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

        <div className="space-y-8">
          {/* 연구 배경 — 내가 어떤 분야에서 무엇을 연구하는지 */}
          <div className="space-y-5">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.12em] text-fg-muted">연구 배경</div>
              <p className="mt-1 text-2xs text-fg-muted">내가 어떤 분야에서 무엇을 연구하는지 알려줘요.</p>
            </div>

            <div>
              <label htmlFor="research-context" className="mb-2 block text-sm font-medium text-fg-secondary">
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
              <label className="mb-2 block text-sm font-medium text-fg-secondary">
                {S.settings.researchAreas}
              </label>
              <AreaPicker value={researchAreas} onChange={setResearchAreas} max={MAX_RESEARCH_AREAS} />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-fg-secondary">
                {S.settings.researchRole}
              </label>
              <Select
                value={researchRole}
                onValueChange={setResearchRole}
                options={RESEARCH_ROLE_OPTIONS.map((opt) => ({ value: opt.key, label: opt.label }))}
                placeholder={S.settings.researchRolePlaceholder}
                aria-label={S.settings.researchRole}
              />
            </div>
          </div>

          <div className="border-t border-border/50" />

          {/* 설명 눈높이 — 분석이 나에게 설명하는 깊이와 관점 */}
          <div className="space-y-5">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.12em] text-fg-muted">설명 눈높이</div>
              <p className="mt-1 text-2xs text-fg-muted">분석이 나에게 설명하는 깊이와 관점을 맞춰요.</p>
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-fg-secondary">
                {S.settings.defaultLevel}
              </label>
              <LevelCards value={defaultLevel} onChange={setDefaultLevel} />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-fg-secondary">
                {S.settings.fieldExpertise}
              </label>
              <SegmentGroup
                options={FIELD_EXPERTISE_OPTIONS}
                value={fieldExpertise}
                onChange={setFieldExpertise}
                ariaLabel={S.settings.fieldExpertise}
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-fg-secondary">
                {S.settings.readingExperience}
              </label>
              <SegmentGroup
                options={READING_EXPERIENCE_OPTIONS}
                value={readingExperience}
                onChange={setReadingExperience}
                ariaLabel={S.settings.readingExperience}
              />
            </div>
          </div>
        </div>
      </section>

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
