import type { Recipe } from '@/lib/api';
import {
  attachEvidence,
  canShowFoundQuote,
  evidenceBadge,
  evidenceMethodLabel,
  parseRecipeParameters,
  resolveDisplayStatus,
  summarizeAnchoredEvidence,
} from '@/lib/evidence';
import { S } from '@/lib/strings';

// 열 순서가 이 파일의 계약이고, 이름 자체는 strings.ts가 쥔다(사용자가 읽는 문자열이라서).
// 이름은 검증 여부를 단정하지 않는다 — (verified) 같은 도장이 이름에 붙어 있으면 미검증 행을
// 채우는 순간 조용한 승격이 되므로, 이름 정리가 노출의 선행 조건이다(DEC-012).
// 상태와 방법 값도 화면과 같은 한국어 라벨로 적는다. 이 CSV는 사람이 읽는 표다.
const H = S.recipe.csvHeader;

export const RECIPE_CSV_HEADER = [
  H.section,
  H.key,
  H.value,
  H.status,
  H.method,
  H.foundQuote,
  H.foundPage,
  H.claimedQuote,
  H.claimedPage,
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
  const evidence = recipe.evidence ?? null;

  // 파라미터는 화면과 같은 파서·결합 규칙을 먼저 돌린다 — CSV와 화면의 행이 어긋나면
  // 근거가 다른 줄에 붙는다. 메타 행의 분모도 여기서 나온 수를 쓴다. 백엔드 summary는
  // attachEvidence의 fail-closed를 모르기 때문에 표에 보이는 수와 어긋난다.
  const anchored = attachEvidence(parseRecipeParameters(data.parameters), evidence);
  const counts = summarizeAnchoredEvidence(anchored);

  rows.push([...RECIPE_CSV_HEADER]);

  // 표가 도구 밖으로 나가도 검증 맥락이 따라가게 메타 행을 남긴다.
  if (evidence) {
    rows.push(plainRow('Meta', 'Verifier', `${evidence.verifier_version}/${evidence.normalizer_version}`));
    rows.push(plainRow('Meta', 'Evidence Verified', `${counts.verified}/${counts.total}`));
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

  anchored.forEach(({ row, anchor }) => {
    const status = resolveDisplayStatus(anchor);
    // 원문에서 찾은 인용을 실을지는 툴팁과 같은 판정을 쓴다 — 두 표면이 갈라지면
    // 화면에서 숨긴 인용이 CSV로 새어 나간다.
    const found = canShowFoundQuote(anchor);
    rows.push([
      'Parameter',
      row.name,
      `${row.value || ''}${row.unit ? ' ' + row.unit : ''}${row.notes ? ' (' + row.notes + ')' : ''}`,
      evidenceBadge(status).label,
      evidenceMethodLabel(anchor?.match_method),
      found ? anchor?.matched_quote ?? '' : '',
      // 인용과 페이지는 한 덩어리로 게이팅한다. 부분 일치 행에 "발견 페이지"만 남으면
      // 찾지도 못한 위치를 발견이라 부르는 셈이라, 열 이름을 정리한 취지가 무너진다.
      found && anchor?.matched_page != null ? String(anchor.matched_page) : '',
      // 주장 열은 "LLM이 뭐라고 했는가"의 기록이라 검증 결과와 무관하게 그대로 싣는다.
      anchor?.claimed_quote ?? '',
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
