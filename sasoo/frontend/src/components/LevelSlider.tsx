import { useId } from 'react';

export const LEVEL_ORDER = ['elementary', 'middle', 'high', 'undergrad', 'masters', 'phd'] as const;
export type LevelKey = (typeof LEVEL_ORDER)[number];

export const LEVEL_LABELS: Record<LevelKey, string> = {
  elementary: '초등학생', middle: '중학생', high: '고등학생',
  undergrad: '학부생', masters: '석사생', phd: '박사생',
};

// 같은 개념(빛의 간섭)을 수준별 문체로 — 슬라이더의 의미를 즉시 체감시키는 프리뷰
const LEVEL_PREVIEWS: Record<LevelKey, string> = {
  elementary: '빛 두 줄기가 만나면 물결처럼 겹쳐서 더 밝아지거나 어두워져요.',
  middle: '두 빛의 파동이 겹치면 마루끼리 만나 밝아지고, 마루와 골이 만나 어두워집니다.',
  high: '두 파동의 위상차가 0이면 보강간섭, π이면 상쇄간섭이 일어나 간섭무늬가 생깁니다.',
  undergrad: '두 간섭 광의 세기는 I = I₁ + I₂ + 2√(I₁I₂)cosΔφ로 위상차에 의해 결정됩니다.',
  masters: '가시도(visibility)는 광원의 시간·공간 결맞음에 의해 제한되며 상호결맞음 함수로 기술됩니다.',
  phd: '부분결맞음 조건에서 간섭항은 상호결맞음 함수 γ₁₂(τ)의 크기와 인수로 완전히 결정되며, van Cittert–Zernike 정리로 광원 분포와 연결됩니다.',
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
