// Phase 5 종합 뷰 — 순수 함수 (React 없음).
// 백엔드가 기획한 VisualizationItem 목록을 종합 뷰의 3개 구획(개념/방법/결과)으로
// 배정하고, 레시피 표를 종합의 key_parameters 순서에 맞춰 추린다.

import type { VisualizationItem } from '@/lib/api';

const METHOD_LIMIT = 3;
const RESULT_LIMIT = 2;
const REPRO_ROW_LIMIT = 5;

export interface AssignedBlocks {
  concept: VisualizationItem | null;
  method: VisualizationItem[];
  result: VisualizationItem[];
}

/**
 * `block`이 있는 항목은 그 값대로 배정한다. 없는 항목(종합 도입 전 논문)은 category로
 * 배정한다: 첫 번째 paperbanana만 concept(나머지 paperbanana는 버림), mermaid는
 * category가 comparison이면 result, 그 외는 method. mindmap은 버린다.
 * 상한은 method 3, result 2이고 초과분은 기획 순서대로 앞에서부터 남긴다.
 */
export function assignBlocks(items: VisualizationItem[]): AssignedBlocks {
  let concept: VisualizationItem | null = null;
  const method: VisualizationItem[] = [];
  const result: VisualizationItem[] = [];
  let sawPaperbanana = false;

  for (const item of items) {
    if (item.block === 'concept') {
      if (!concept) concept = item;
      continue;
    }
    if (item.block === 'method') {
      method.push(item);
      continue;
    }
    if (item.block === 'result') {
      result.push(item);
      continue;
    }

    // block 없음 (기존 논문): category/tool로 배정
    if (item.tool === 'paperbanana') {
      if (!sawPaperbanana) {
        if (!concept) concept = item;
        sawPaperbanana = true;
      }
      continue;
    }
    if (item.tool === 'mermaid') {
      if (item.diagram_type === 'mindmap') continue;
      if (item.category === 'comparison') {
        result.push(item);
      } else {
        method.push(item);
      }
    }
  }

  return {
    concept,
    method: method.slice(0, METHOD_LIMIT),
    result: result.slice(0, RESULT_LIMIT),
  };
}

/** unit이 "-"이거나 비면 value만, 아니면 "value unit". */
export function formatMetricValue(m: { value: string; unit: string }): string {
  const unit = m.unit?.trim();
  if (!unit || unit === '-') return m.value;
  // 퍼센트와 각도는 숫자에 붙여 쓴다(60%, 30°).
  return /^[%‰°]/.test(unit) ? `${m.value}${unit}` : `${m.value} ${unit}`;
}

export interface ReproRow {
  name: string;
  value: string;
  notes: string;
}

/**
 * recipe.parameters(각 {name, value, unit, notes})에서 names 순서대로 이름이
 * 일치하는 행만 고른다(공백 제거 + 소문자화 비교). 최대 5행. showNotes는 notes가
 * 하나라도 비어 있지 않을 때만 true.
 */
export function pickReproRows(
  recipe: Record<string, unknown> | null,
  names: { name: string }[]
): { rows: ReproRow[]; showNotes: boolean } {
  const normalize = (s: string) => s.trim().toLowerCase();

  const parameters = Array.isArray(recipe?.parameters)
    ? (recipe.parameters as Record<string, unknown>[])
    : [];

  const byNormalizedName = new Map<string, Record<string, unknown>>();
  for (const p of parameters) {
    const name = typeof p?.name === 'string' ? p.name : '';
    if (!name) continue;
    const key = normalize(name);
    if (!byNormalizedName.has(key)) byNormalizedName.set(key, p);
  }

  const rows: ReproRow[] = [];
  for (const { name: wanted } of names) {
    if (rows.length >= REPRO_ROW_LIMIT) break;
    const match = byNormalizedName.get(normalize(wanted));
    if (!match) continue;

    const value = typeof match.value === 'string' ? match.value : String(match.value ?? '');
    const unit = typeof match.unit === 'string' ? match.unit : '';
    const notes = typeof match.notes === 'string' ? match.notes : '';

    rows.push({
      name: typeof match.name === 'string' ? match.name : wanted,
      value: formatMetricValue({ value, unit }),
      notes,
    });
  }

  const showNotes = rows.some((r) => r.notes.trim() !== '');
  return { rows, showNotes };
}
