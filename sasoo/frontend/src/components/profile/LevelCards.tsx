import { useRef } from 'react';
import type { KeyboardEvent } from 'react';
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
 * LEVEL_ORDER/LevelKey는 LevelSlider.tsx의 export를 재사용한다 - 같은 6개
 * 값을 두 번 선언하지 않기 위해서다. LevelSlider는 UploadPanel(compact 모드)과
 * Library가 여전히 쓰고 있어 삭제하지 않았다.
 *
 * roving tabIndex(선택된 카드만 tabIndex=0)를 쓰므로 WAI-ARIA radiogroup
 * 키보드 패턴이 짝을 이뤄야 한다: 화살표로 이동하며 선택까지 함께 바뀌고,
 * 포커스도 새 항목으로 옮겨가야 Tab만으로 나머지 카드에 도달 못 하는 문제가
 * 생기지 않는다. 교체 전 LevelSlider(<input type="range">)는 화살표 키로
 * 완전히 조작 가능했으므로 이 카드도 동등한 키보드 접근성을 갖춰야 한다.
 */
export function LevelCards({ value, onChange }: Props) {
  const buttonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const count = LEVEL_ORDER.length;
    let nextIndex: number | null = null;

    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowRight':
        nextIndex = (index + 1) % count;
        break;
      case 'ArrowUp':
      case 'ArrowLeft':
        nextIndex = (index - 1 + count) % count;
        break;
      case 'Home':
        nextIndex = 0;
        break;
      case 'End':
        nextIndex = count - 1;
        break;
      default:
        return;
    }

    event.preventDefault();
    onChange(LEVEL_ORDER[nextIndex]);
    buttonRefs.current[nextIndex]?.focus();
  };

  return (
    <div role="radiogroup" aria-label={S.settings.defaultLevel} className="grid gap-2">
      {LEVEL_ORDER.map((level, index) => {
        const selected = value === level;
        return (
          <button
            key={level}
            ref={(el) => {
              buttonRefs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            className={`level-card ${selected ? 'level-card-active' : 'level-card-inactive'}`}
            onClick={() => onChange(level)}
            onKeyDown={(event) => handleKeyDown(event, index)}
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
