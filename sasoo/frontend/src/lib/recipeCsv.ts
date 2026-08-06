import type { Recipe } from '@/lib/api';
import { attachEvidence, parseRecipeParameters, resolveDisplayStatus } from '@/lib/evidence';

// 기존 3열(Section/Key/Value)의 의미는 그대로 두고 근거 6열을 뒤에 붙인다.
// 상태 코드는 번역 라벨이 아니라 코드값 그대로 넣는다 — 기계 처리와 재현을 위해서다.
export const RECIPE_CSV_HEADER = [
  'Section',
  'Key',
  'Value',
  'Evidence Status',
  'Evidence Method',
  'Evidence Page',
  'Evidence Quote (verified)',
  'Claimed Quote (unverified)',
  'Claimed Page',
] as const;

const COLUMN_COUNT = RECIPE_CSV_HEADER.length;

function plainRow(section: string, key: string, value: string): string[] {
  return [section, key, value, ...Array(COLUMN_COUNT - 3).fill('')];
}

function escapeCell(cell: string): string {
  const value = String(cell).replace(/"/g, '""');
  return value.includes(',') || value.includes('"') || value.includes('\n') ? `"${value}"` : value;
}

export function generateCsvFromRecipe(recipe: Recipe): string {
  const data = recipe.recipe as Record<string, unknown>;
  const rows: string[][] = [];

  rows.push([...RECIPE_CSV_HEADER]);

  // 표가 도구 밖으로 나가도 검증 맥락이 따라가게 메타 행을 남긴다.
  const evidence = recipe.evidence ?? null;
  if (evidence) {
    rows.push(plainRow('Meta', 'Verifier', `${evidence.verifier_version}/${evidence.normalizer_version}`));
    rows.push(plainRow('Meta', 'Evidence Verified', `${evidence.summary.verified}/${evidence.summary.total}`));
  } else {
    rows.push(plainRow('Meta', 'Verifier', 'not_run'));
  }

  rows.push(plainRow('Info', 'Title', String(data.title || '')));
  rows.push(plainRow('Info', 'Objective', String(data.objective || '')));
  rows.push(plainRow('Info', 'Confidence', data.confidence != null ? `${(Number(data.confidence) * 100).toFixed(0)}%` : ''));
  rows.push(plainRow('Info', 'Reproducibility', data.reproducibility_score != null ? `${(Number(data.reproducibility_score) * 100).toFixed(0)}%` : ''));

  const materials = (data.materials as string[]) || [];
  materials.forEach((m, i) => rows.push(plainRow('Material', `#${i + 1}`, m)));

  const equipment = (data.equipment as string[]) || [];
  equipment.forEach((e, i) => rows.push(plainRow('Equipment', `#${i + 1}`, e)));

  // 파라미터는 화면과 같은 파서를 쓴다 — CSV와 화면의 행이 어긋나면 근거가 다른 줄에 붙는다.
  const anchored = attachEvidence(parseRecipeParameters(data.parameters), evidence);
  anchored.forEach(({ row, anchor }) => {
    const status = resolveDisplayStatus(anchor);
    const verified = status === 'VERIFIED';
    rows.push([
      'Parameter',
      row.name,
      `${row.value || ''}${row.unit ? ' ' + row.unit : ''}${row.notes ? ' (' + row.notes + ')' : ''}`,
      status,
      anchor?.match_method ?? '',
      anchor?.matched_page != null ? String(anchor.matched_page) : '',
      // 확인된 인용만 이 열에 넣는다. 미확인 인용을 여기 넣으면 CSV가 "검증된 근거표"로
      // 유통되며 거짓을 퍼뜨린다.
      verified ? anchor?.matched_quote ?? '' : '',
      verified ? '' : anchor?.claimed_quote ?? '',
      anchor?.claimed_page != null ? String(anchor.claimed_page) : '',
    ]);
  });

  const steps = (data.steps as string[]) || [];
  steps.forEach((s, i) => rows.push(plainRow('Step', `#${i + 1}`, s)));

  const notes = (data.critical_notes as string[]) || [];
  notes.forEach((n, i) => rows.push(plainRow('Critical Note', `#${i + 1}`, n)));

  if (data.expected_results) rows.push(plainRow('Info', 'Expected Results', String(data.expected_results)));
  if (data.safety_notes) rows.push(plainRow('Info', 'Safety Notes', String(data.safety_notes)));

  return rows.map((row) => row.map(escapeCell).join(',')).join('\n');
}
