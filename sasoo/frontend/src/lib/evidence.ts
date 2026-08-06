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
      return { row, anchor: null };
    }
    return { row, anchor };
  });
}

export function resolveDisplayStatus(anchor: EvidenceAnchor | null): EvidenceDisplayStatus {
  return anchor?.display_status ?? 'UNVERIFIED_NOT_RUN';
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

export function evidenceTooltip(anchor: EvidenceAnchor | null): string {
  const status = resolveDisplayStatus(anchor);
  const label = evidenceBadge(status).label;
  if (!anchor) {
    return `${label}\n${S.recipe.evidence.notRunNotice}`;
  }

  const lines: string[] = [label];

  if (anchor.display_status === 'VERIFIED' && anchor.matched_quote) {
    lines.push(`${S.recipe.evidence.verifiedQuote}: "${anchor.matched_quote}"`);
  } else if (anchor.claimed_quote) {
    // 확인되지 않은 인용을 확인된 근거처럼 보이게 하지 않는다.
    lines.push(`${S.recipe.evidence.claimedQuote}: "${anchor.claimed_quote}"`);
  }

  if (typeof anchor.matched_page === 'number') {
    lines.push(
      anchor.display_status === 'VERIFIED'
        ? S.recipe.evidence.confirmedPage(anchor.matched_page)
        : S.recipe.evidence.candidatePage(anchor.matched_page),
    );
  }
  if (typeof anchor.claimed_page === 'number' && anchor.claimed_page !== anchor.matched_page) {
    lines.push(S.recipe.evidence.claimedPageNote(anchor.claimed_page));
  }
  if (anchor.match_method && METHOD_LABEL[anchor.match_method]) {
    lines.push(METHOD_LABEL[anchor.match_method]);
  }

  lines.push(S.recipe.evidence.disclaimer);
  return lines.join('\n');
}
