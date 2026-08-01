import { useId } from 'react';
import { S } from '@/lib/strings';

export const LEVEL_ORDER = ['elementary', 'middle', 'high', 'undergrad', 'masters', 'phd'] as const;
export type LevelKey = (typeof LEVEL_ORDER)[number];

// S.levels(strings.ts)가 단일 출처다 — 라벨/프리뷰 문장은 거기서 파생한다.
export const LEVEL_LABELS: Record<LevelKey, string> = {
  elementary: S.levels.elementary.label,
  middle: S.levels.middle.label,
  high: S.levels.high.label,
  undergrad: S.levels.undergrad.label,
  masters: S.levels.masters.label,
  phd: S.levels.phd.label,
};

const LEVEL_PREVIEWS: Record<LevelKey, string> = {
  elementary: S.levels.elementary.preview,
  middle: S.levels.middle.preview,
  high: S.levels.high.preview,
  undergrad: S.levels.undergrad.preview,
  masters: S.levels.masters.preview,
  phd: S.levels.phd.preview,
};

interface Props {
  value: string;
  onChange: (key: LevelKey) => void;
  compact?: boolean; // true면 프리뷰 문장 숨김 (결과 화면용)
  disabled?: boolean; // true면 상호작용 차단 (재작성 로딩 중)
}

export default function LevelSlider({ value, onChange, compact = false, disabled = false }: Props) {
  const id = useId();
  const index = Math.max(0, LEVEL_ORDER.indexOf(value as LevelKey));
  const current = LEVEL_ORDER[index];
  return (
    <div className={disabled ? 'level-slider is-disabled' : 'level-slider'}>
      <input
        id={id}
        type="range"
        min={0}
        max={LEVEL_ORDER.length - 1}
        step={1}
        value={index}
        onChange={(e) => onChange(LEVEL_ORDER[Number(e.target.value)])}
        disabled={disabled}
        aria-label="설명 수준"
        aria-valuetext={LEVEL_LABELS[current]}
        list={`${id}-ticks`}
      />
      <div className="level-slider-labels">
        {LEVEL_ORDER.map((key) => (
          <button
            key={key}
            type="button"
            disabled={disabled}
            className={key === current ? 'level-label active' : 'level-label'}
            onClick={() => onChange(key)}
          >
            {LEVEL_LABELS[key]}
          </button>
        ))}
      </div>
      {!compact && (
        <p className="level-preview" aria-live="polite">{LEVEL_PREVIEWS[current]}</p>
      )}
    </div>
  );
}
