import type { EvidenceAnchor, EvidenceDisplayStatus, RecipeEvidence } from '@/lib/api';
import { S } from '@/lib/strings';

// ---------------------------------------------------------------------------
// 파라미터 파싱
// ---------------------------------------------------------------------------
// RecipeCard 안에 있던 파서를 그대로 옮겼다. 백엔드 검증기(services/evidence_verifier.py의
// iter_recipe_parameters)가 이 규칙과 1:1로 같아야 target_index가 밀리지 않는다.
// 규칙을 바꾸면 반드시 양쪽을 함께 바꾼다.

export interface RecipeParameterRow {
  index: number;
  name: string;
  value: string;
  unit: string;
  notes: string;
}

export function parseRecipeParameters(raw: unknown): RecipeParameterRow[] {
  const rows: RecipeParameterRow[] = [];
  if (!Array.isArray(raw)) return rows;

  raw.forEach((p: unknown) => {
    if (typeof p === 'object' && p !== null) {
      const obj = p as Record<string, unknown>;
      rows.push({
        index: rows.length,
        name: String(obj.name || obj.Name || obj.parameter || obj.key || ''),
        value: String(obj.value || obj.Value || obj.val || ''),
        unit: String(obj.unit || obj.Unit || obj.units || ''),
        notes: String(obj.notes || obj.Notes || obj.note || obj.context || ''),
      });
    } else if (typeof p === 'string') {
      // "Temperature: 500 C" 형식
      const match = p.match(/^(.+?):\s*(.+)$/);
      if (match) {
        rows.push({ index: rows.length, name: match[1].trim(), value: match[2].trim(), unit: '', notes: '' });
      } else {
        rows.push({ index: rows.length, name: p, value: '', unit: '', notes: '' });
      }
    }
  });

  return rows;
}

// ---------------------------------------------------------------------------
// 앵커 결합 (fail closed)
// ---------------------------------------------------------------------------

export interface AnchoredParameter {
  row: RecipeParameterRow;
  anchor: EvidenceAnchor | null;
}

export function attachEvidence(
  rows: RecipeParameterRow[],
  evidence: RecipeEvidence | null | undefined,
): AnchoredParameter[] {
  const byIndex = new Map<number, EvidenceAnchor>();
  for (const anchor of evidence?.anchors ?? []) {
    byIndex.set(anchor.target_index, anchor);
  }

  return rows.map((row) => {
    const anchor = byIndex.get(row.index) ?? null;
    // 인덱스가 밀려 엉뚱한 파라미터에 근거가 붙는 것보다 "근거 없음"이 정직하다.
    if (anchor && (anchor.target_label ?? '').trim() !== row.name.trim()) {
      // 이 분기가 조용히 자주 타면 백엔드 iter_recipe_parameters와 프론트
      // parseRecipeParameters의 명명 규칙이 드리프트했다는 신호다 — "이상하게 낮은
      // verified 수" 말고는 알아챌 방법이 없으므로 개발 중에는 콘솔에 남긴다.
      // 프로덕션 사용자에게는 소음이라 DEV 빌드에서만 찍는다.
      if (import.meta.env.DEV) {
        console.warn('[evidence] anchor label mismatch — hiding anchor', {
          index: row.index,
          expected: row.name,
          got: anchor.target_label,
        });
      }
      return { row, anchor: null };
    }
    return { row, anchor };
  });
}

export function resolveDisplayStatus(anchor: EvidenceAnchor | null): EvidenceDisplayStatus {
  return anchor?.display_status ?? 'UNVERIFIED_NOT_RUN';
}

// ---------------------------------------------------------------------------
// 요약 배지 (fail-closed로 숨겨진 앵커까지 반영한 화면 실제 수치)
// ---------------------------------------------------------------------------
// 백엔드 evidence.summary는 attachEvidence의 label 불일치 fail-closed를 모른다 — 그
// 분모·분자를 그대로 배지에 쓰면 표에 실제로 보이는 검증 수와 배지가 어긋난다. 항상
// 화면에 붙은 anchored 결과에서 다시 센다.

export interface EvidenceSummaryCounts {
  verified: number;
  total: number;
}

export function summarizeAnchoredEvidence(anchored: AnchoredParameter[]): EvidenceSummaryCounts {
  const verified = anchored.filter((item) => resolveDisplayStatus(item.anchor) === 'VERIFIED').length;
  return { verified, total: anchored.length };
}

/** 부분 검증(1/N)은 절대 success 톤을 쓰지 않는다 — 전부 검증됐을 때만 초록이다. */
export function evidenceSummaryTone(verified: number, total: number): 'success' | 'warning' | 'neutral' {
  if (total > 0 && verified === total) return 'success';
  if (verified > 0) return 'warning';
  return 'neutral';
}

// ---------------------------------------------------------------------------
// 배지 / 툴팁 / 이동 대상
// ---------------------------------------------------------------------------

export interface EvidenceBadge {
  label: string;
  tone: 'neutral' | 'accent' | 'danger' | 'warning' | 'success';
  icon: 'success' | 'warning' | 'error' | 'info';
  verified: boolean;
}

const BADGE_STYLE: Record<EvidenceDisplayStatus, { tone: EvidenceBadge['tone']; icon: EvidenceBadge['icon'] }> = {
  VERIFIED: { tone: 'success', icon: 'success' },
  UNVERIFIED_PAGE_MISMATCH: { tone: 'warning', icon: 'warning' },
  UNVERIFIED_VALUE_MISMATCH: { tone: 'danger', icon: 'warning' },
  UNVERIFIED_INFERRED: { tone: 'warning', icon: 'info' },
  UNVERIFIED_PARTIAL: { tone: 'warning', icon: 'warning' },
  UNVERIFIED_AMBIGUOUS: { tone: 'warning', icon: 'warning' },
  UNVERIFIED_NOT_FOUND: { tone: 'danger', icon: 'error' },
  UNVERIFIED_NO_QUOTE: { tone: 'neutral', icon: 'info' },
  UNVERIFIED_NO_TEXT_LAYER: { tone: 'neutral', icon: 'info' },
  UNVERIFIED_STALE_SOURCE: { tone: 'neutral', icon: 'warning' },
  UNVERIFIED_ERROR: { tone: 'danger', icon: 'error' },
  UNVERIFIED_NOT_RUN: { tone: 'neutral', icon: 'info' },
};

export function evidenceBadge(status: EvidenceDisplayStatus): EvidenceBadge {
  const style = BADGE_STYLE[status] ?? BADGE_STYLE.UNVERIFIED_ERROR;
  return {
    label: S.recipe.evidence.status[status] ?? S.recipe.evidence.status.UNVERIFIED_ERROR,
    tone: style.tone,
    icon: style.icon,
    verified: status === 'VERIFIED',
  };
}

/** 이동 가능한 페이지와 그 페이지가 확인된 위치인지 여부. 확인되지 않은 페이지는 "후보"다. */
export function evidenceTarget(anchor: EvidenceAnchor | null): { page: number; confirmed: boolean } | null {
  if (!anchor) return null;
  if (typeof anchor.matched_page === 'number' && anchor.matched_page > 0) {
    return { page: anchor.matched_page, confirmed: anchor.display_status === 'VERIFIED' };
  }
  if (typeof anchor.claimed_page === 'number' && anchor.claimed_page > 0) {
    return { page: anchor.claimed_page, confirmed: false };
  }
  return null;
}

const METHOD_LABEL: Record<string, string> = {
  exact: S.recipe.evidence.method.exact,
  normalized: S.recipe.evidence.method.normalized,
  partial: S.recipe.evidence.method.partial,
};

/** 화면과 CSV가 같은 어휘를 쓰게 한다. 모르는 코드는 버리지 않고 원본을 그대로 돌려준다. */
export function evidenceMethodLabel(method: string | null | undefined): string {
  if (!method) return '';
  return METHOD_LABEL[method] ?? method;
}

// ---------------------------------------------------------------------------
// 원문에서 찾은 인용의 노출 범위 (DEC-012)
// ---------------------------------------------------------------------------
// 검증기가 "인용이 원문에 축자 또는 표기 정규화로 존재한다"를 보장하는 버킷만 들어간다.
// PAGE_MISMATCH는 페이지만 어긋났을 뿐 인용 자체는 원문에서 찾은 것이라 노출해도 된다.
// partial은 위조 인용 81%가 통과한 실측이 있으니 이 집합을 절대 넓히지 마라 —
// 툴팁과 CSV가 같은 집합을 보므로 여기 한 줄이 두 표면을 동시에 무너뜨린다.
const FOUND_QUOTE_STATUSES: ReadonlySet<EvidenceDisplayStatus> = new Set([
  'VERIFIED',
  'UNVERIFIED_PAGE_MISMATCH',
]);

/** matched_quote를 사용자에게 보여도 되는가. 검증 도장 여부는 별개다. */
export function canShowFoundQuote(anchor: EvidenceAnchor | null): boolean {
  if (!anchor?.matched_quote) return false;
  return FOUND_QUOTE_STATUSES.has(resolveDisplayStatus(anchor));
}

export function evidenceTooltip(anchor: EvidenceAnchor | null): string {
  const status = resolveDisplayStatus(anchor);
  const label = evidenceBadge(status).label;
  if (!anchor) {
    return `${label}\n${S.recipe.evidence.notRunNotice}`;
  }

  const lines: string[] = [label];

  // DEC-012 — 검증 도장 없이 원문 인용만 보여주는 near-miss 경로.
  const nearMissQuote = canShowFoundQuote(anchor) && anchor.display_status !== 'VERIFIED';

  if (anchor.display_status === 'VERIFIED' && anchor.matched_quote) {
    lines.push(`${S.recipe.evidence.verifiedQuote}: "${anchor.matched_quote}"`);
  } else if (nearMissQuote) {
    // 검증 도장은 붙이지 않는다. 발견 페이지를 라벨에 넣어 아래 주장 페이지와 나란히 읽히게 한다.
    lines.push(`${S.recipe.evidence.foundQuote(anchor.matched_page)}: "${anchor.matched_quote}"`);
  } else if (anchor.claimed_quote) {
    // 확인되지 않은 인용을 확인된 근거처럼 보이게 하지 않는다.
    lines.push(`${S.recipe.evidence.claimedQuote}: "${anchor.claimed_quote}"`);
  }

  // 발견 인용 라벨이 이미 페이지를 달고 있으면 같은 번호를 두 번 적지 않는다.
  if (typeof anchor.matched_page === 'number' && !nearMissQuote) {
    lines.push(
      anchor.display_status === 'VERIFIED'
        ? S.recipe.evidence.confirmedPage(anchor.matched_page)
        : S.recipe.evidence.candidatePage(anchor.matched_page),
    );
  }
  if (typeof anchor.claimed_page === 'number' && anchor.claimed_page !== anchor.matched_page) {
    lines.push(S.recipe.evidence.claimedPageNote(anchor.claimed_page));
  }
  // 툴팁과 CSV가 같은 헬퍼를 쓴다. 모르는 코드를 툴팁만 조용히 버리면 두 표면의 어휘가 갈린다.
  const method = evidenceMethodLabel(anchor.match_method);
  if (method) {
    lines.push(method);
  }

  lines.push(S.recipe.evidence.disclaimer);
  return lines.join('\n');
}
