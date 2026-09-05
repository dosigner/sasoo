import { S } from '@/lib/strings';

// 키는 백엔드 analysis_context.py의 AREA_LABELS와 집합이 같아야 한다(test_analysis_context.py가 고정).
const AREAS = [
  'optics_photonics',
  'ai_ml',
  'robotics_control',
  'electrical_electronics',
  'computer_science',
  'physics_math',
  'bio_medical',
  'other',
] as const;

interface Props {
  value: string[];
  onChange: (next: string[]) => void;
  max?: number;
}

/**
 * 연구 분야 선택.
 *
 * 검색 팝오버를 쓰지 않는다. 선택지가 8개뿐이라 전부 펼쳐 보이는 편이
 * 빠르다. 기존 구현은 팝오버를 열고 검색해서 고른 뒤 아래 칩으로 다시
 * 보여주는 3단 구조였다.
 *
 * 칩에 아이콘을 붙이지 않는다. 16px 선 아이콘 8종은 서로 구분되지 않고
 * 바로 옆 라벨과 정보가 겹쳐 시각 잡음만 됐다.
 *
 * 상한(3개)에 도달하면 고르지 않은 칩만 비활성화한다. 선택된 칩은 계속
 * 해제할 수 있어야 한다.
 *
 * 잠긴 칩은 disabled라 포커스를 받지 못해 스크린리더가 상한 도달 사유를
 * 읽을 수 없다 - disabled 요소는 접근성 트리에서 아예 제외되기 때문이다.
 * 그래서 도움말 문구(researchAreasMaxReached)에 aria-live="polite"를 달아
 * 상한에 도달하는 순간 스크린리더가 그 문구 변화를 능동적으로 읽게 한다.
 * 브리프의 버튼 구조(role/aria-checked/disabled)는 그대로 두고 문구
 * 컨테이너만 보완했다.
 */
export function AreaPicker({ value, onChange, max = 3 }: Props) {
  const atMax = value.length >= max;

  const toggle = (id: string) => {
    if (value.includes(id)) {
      onChange(value.filter((v) => v !== id));
      return;
    }
    if (atMax) return;
    onChange([...value, id]);
  };

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {AREAS.map((id) => {
          const selected = value.includes(id);
          const blocked = atMax && !selected;
          const className = blocked
            ? 'area-chip area-chip-disabled'
            : selected
              ? 'area-chip area-chip-active'
              : 'area-chip area-chip-inactive';

          return (
            <button
              key={id}
              type="button"
              role="checkbox"
              aria-checked={selected}
              aria-disabled={blocked}
              disabled={blocked}
              className={className}
              onClick={() => toggle(id)}
            >
              {S.areas[id]}
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-fg-muted" aria-live="polite">
        {atMax ? S.settings.researchAreasMaxReached : S.settings.researchAreasHelper}
      </p>
    </div>
  );
}

export default AreaPicker;
