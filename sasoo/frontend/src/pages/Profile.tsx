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
import { Select, Popover } from '@/components/ui';

// ---------------------------------------------------------------------------
// 연구자 프로필 — 연구 배경과 기본 설명 수준을 관리하는 전용 페이지.
// analysis_focus(분석 초점)는 논문마다 다르므로 여기 두지 않고 업로드 화면에서만 받는다.
// ---------------------------------------------------------------------------

// 주요 연구 분야 — 검색형 멀티셀렉트, 최대 3개. key는 백엔드 research_areas로 그대로 저장된다.
const MAX_RESEARCH_AREAS = 3;
const RESEARCH_AREA_OPTIONS = [
  { key: 'optics_photonics', label: '광학·포토닉스' },
  { key: 'ai_ml', label: 'AI·머신러닝' },
  { key: 'robotics_control', label: '로보틱스·제어' },
  { key: 'electrical_electronics', label: '전기·전자' },
  { key: 'computer_science', label: '컴퓨터과학' },
  { key: 'physics_math', label: '물리·수학' },
  { key: 'bio_medical', label: '바이오·의생명' },
  { key: 'other', label: '기타' },
] as const;
const RESEARCH_AREA_LABELS: Record<string, string> = Object.fromEntries(
  RESEARCH_AREA_OPTIONS.map((opt) => [opt.key, opt.label])
);

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

// 주요 연구 분야 — 검색형 멀티셀렉트 드롭다운 + 선택 칩(개별 삭제 가능)
function ResearchAreaSelect({
  value,
  onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const atMax = value.length >= MAX_RESEARCH_AREAS;
  const filtered = RESEARCH_AREA_OPTIONS.filter((opt) => opt.label.includes(search.trim()));

  const toggle = (key: string) => {
    if (value.includes(key)) {
      onChange(value.filter((k) => k !== key));
    } else if (!atMax) {
      onChange([...value, key]);
    }
  };

  return (
    <div>
      <Popover.Root
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setSearch('');
        }}
      >
        <Popover.Trigger asChild>
          <button
            type="button"
            className="input flex w-full items-center justify-between gap-2 text-left text-fg-muted"
          >
            <span>{S.settings.researchAreasPlaceholder}</span>
            <AppIcon name="chevron-down" className="h-4 w-4 shrink-0 text-fg-muted" />
          </button>
        </Popover.Trigger>
        <Popover.Content align="start" className="w-[20rem] max-w-[90vw] p-2">
          <div className="relative mb-2">
            <AppIcon
              name="search"
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-fg-muted"
            />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={S.settings.researchAreasSearchPlaceholder}
              className="input pl-8 text-sm"
              autoFocus
            />
          </div>
          <div className="max-h-56 space-y-0.5 overflow-y-auto">
            {filtered.map((opt) => {
              const selected = value.includes(opt.key);
              const disabled = !selected && atMax;
              return (
                <button
                  key={opt.key}
                  type="button"
                  disabled={disabled}
                  aria-pressed={selected}
                  onClick={() => toggle(opt.key)}
                  className={`flex w-full items-center justify-between rounded-control px-2.5 py-1.5 text-left text-sm transition-colors ${
                    selected
                      ? 'bg-accent/10 text-accent'
                      : disabled
                        ? 'cursor-not-allowed text-fg-muted opacity-40'
                        : 'text-fg hover:bg-surface-hover'
                  }`}
                >
                  {opt.label}
                  {selected && <AppIcon name="success" className="h-3.5 w-3.5" />}
                </button>
              );
            })}
            {filtered.length === 0 && (
              <p className="px-2.5 py-2 text-xs text-fg-muted">{S.settings.researchAreasNoMatch}</p>
            )}
          </div>
          {atMax && (
            <p className="mt-2 px-1 text-2xs text-fg-muted">{S.settings.researchAreasMaxReached}</p>
          )}
        </Popover.Content>
      </Popover.Root>

      {value.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {value.map((key) => {
            const label = RESEARCH_AREA_LABELS[key] ?? key;
            return (
              <span
                key={key}
                className="inline-flex items-center gap-1.5 rounded-full border border-accent/20 bg-accent/10 px-3 py-1 text-xs text-accent"
              >
                {label}
                <button
                  type="button"
                  onClick={() => onChange(value.filter((k) => k !== key))}
                  aria-label={S.settings.removeAreaLabel(label)}
                  className="text-accent/70 transition-colors hover:text-accent"
                >
                  <AppIcon name="close" className="h-3 w-3" />
                </button>
              </span>
            );
          })}
        </div>
      )}
      <p className="mt-1.5 text-2xs text-fg-muted">{S.settings.researchAreasHelper}</p>
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

  const hasChanges =
    researchContext !== baseline.research_context ||
    defaultLevel !== baseline.default_explanation_level ||
    JSON.stringify(researchAreas) !== JSON.stringify(baseline.research_areas) ||
    fieldExpertise !== baseline.field_expertise ||
    readingExperience !== baseline.reading_experience ||
    researchRole !== baseline.research_role;

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
      toast.success(S.toast.settingsSaved);
    } catch (err) {
      setError(err instanceof Error ? err.message : S.settings.saveFailed);
      if (err instanceof Error) console.warn('[profile] save error:', err.message);
      toast.error(S.toast.settingsFailed);
    } finally {
      setSaving(false);
    }
  }, [researchContext, defaultLevel, researchAreas, fieldExpertise, readingExperience, researchRole, toast]);

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
              <ResearchAreaSelect value={researchAreas} onChange={setResearchAreas} />
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
              <LevelSlider value={defaultLevel} onChange={setDefaultLevel} />
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
    </div>
  );
}
