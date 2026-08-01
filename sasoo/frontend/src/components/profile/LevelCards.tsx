import { S } from '@/lib/strings';
import { LEVEL_ORDER, type LevelKey } from '@/components/LevelSlider';

interface Props {
  value: LevelKey;
  onChange: (next: LevelKey) => void;
}

/**
 * 설명 수준 선택.
 *
 * 슬라이더를 쓰지 않는다. "석사생"이라는 라벨만 보고 고르는 것보다, 그 수준의
 * 실제 설명 문장을 보고 고르는 편이 정확하다.
 *
 * 값이 순서를 갖긴 하지만(초등 -> 박사) 사용자가 하는 일은 "내 눈높이 하나
 * 고르기"이지 "정도를 조절하기"가 아니다.
 *
 * LEVEL_ORDER/LevelKey는 LevelSlider.tsx의 export를 재사용한다 — 같은 6개
 * 값을 두 번 선언하지 않기 위해서다. LevelSlider는 UploadPanel(compact 모드)과
 * Library가 여전히 쓰고 있어 삭제하지 않았다.
 */
export function LevelCards({ value, onChange }: Props) {
  return (
    <div role="radiogroup" aria-label={S.settings.defaultLevel} className="grid gap-2">
      {LEVEL_ORDER.map((level) => {
        const selected = value === level;
        return (
          <button
            key={level}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            className={`level-card ${selected ? 'level-card-active' : 'level-card-inactive'}`}
            onClick={() => onChange(level)}
          >
            <span className="text-sm font-medium text-fg">{S.levels[level].label}</span>
            <span className="text-xs leading-relaxed text-fg-muted">
              {S.levels[level].preview}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export default LevelCards;
