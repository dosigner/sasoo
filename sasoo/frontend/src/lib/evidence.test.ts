import { describe, expect, it } from 'vitest';
import type { EvidenceAnchor, EvidenceDisplayStatus, RecipeEvidence } from '@/lib/api';
import {
  attachEvidence,
  evidenceBadge,
  evidenceTarget,
  evidenceTooltip,
  parseRecipeParameters,
  resolveDisplayStatus,
} from '@/lib/evidence';

function anchor(overrides: Partial<EvidenceAnchor> = {}): EvidenceAnchor {
  return {
    target_index: 0,
    target_key: 'p000:wavelength',
    target_label: 'wavelength',
    source_tag: 'explicit',
    claimed_quote: 'a wavelength of 1550 nm',
    claimed_page: 4,
    quote_status: 'verified_normalized',
    page_status: 'match',
    value_status: 'value_in_quote',
    display_status: 'VERIFIED',
    match_method: 'normalized',
    match_ratio: 1,
    matched_quote: 'a wave-\nlength of 1550 nm',
    matched_page: 4,
    bbox: [72, 700, 300, 715],
    corpus: 'pdf_text',
    failure_detail: null,
    verifier_version: 'ev1',
    normalizer_version: 'norm-v1',
    ...overrides,
  };
}

function evidence(anchors: EvidenceAnchor[]): RecipeEvidence {
  return {
    verifier_version: 'ev1',
    normalizer_version: 'norm-v1',
    summary: { total: anchors.length, verified: 0, by_display_status: {} },
    anchors,
  };
}

describe('parseRecipeParameters — 백엔드 검증기와 같은 규칙으로 센다', () => {
  it('object와 string만 행이 되고 index가 연속으로 붙는다', () => {
    const rows = parseRecipeParameters([
      { name: 'a', value: '1', unit: 'nm', notes: 'n' },
      'Temperature: 500 C',
      42,
      null,
      { parameter: 'b', val: '2' },
    ]);
    expect(rows.map((row) => row.index)).toEqual([0, 1, 2]);
    expect(rows.map((row) => row.name)).toEqual(['a', 'Temperature', 'b']);
    expect(rows[1].value).toBe('500 C');
    expect(rows[2].value).toBe('2');
  });

  it('배열이 아니면 빈 목록이다', () => {
    expect(parseRecipeParameters(undefined)).toEqual([]);
    expect(parseRecipeParameters('nope')).toEqual([]);
  });
});

describe('attachEvidence — label 불일치는 fail closed', () => {
  it('index로 결합한다', () => {
    const rows = parseRecipeParameters([{ name: 'wavelength', value: '1550' }]);
    const [first] = attachEvidence(rows, evidence([anchor()]));
    expect(first.anchor?.target_key).toBe('p000:wavelength');
  });

  it('label이 다르면 앵커를 숨긴다 (엉뚱한 근거보다 근거 없음이 정직하다)', () => {
    const rows = parseRecipeParameters([{ name: 'laser_power', value: '3.2' }]);
    const [first] = attachEvidence(rows, evidence([anchor()]));
    expect(first.anchor).toBeNull();
    expect(resolveDisplayStatus(first.anchor)).toBe('UNVERIFIED_NOT_RUN');
  });

  it('evidence가 null이면 전 행이 검증 미실행이다', () => {
    const rows = parseRecipeParameters([{ name: 'a', value: '1' }, { name: 'b', value: '2' }]);
    const attached = attachEvidence(rows, null);
    expect(attached.every((item) => item.anchor === null)).toBe(true);
    expect(attached.map((item) => resolveDisplayStatus(item.anchor))).toEqual([
      'UNVERIFIED_NOT_RUN',
      'UNVERIFIED_NOT_RUN',
    ]);
  });

  it('앵커가 파라미터보다 적어도 남는 행은 미실행으로 남는다', () => {
    const rows = parseRecipeParameters([{ name: 'wavelength', value: '1' }, { name: 'power', value: '2' }]);
    const attached = attachEvidence(rows, evidence([anchor()]));
    expect(attached[0].anchor).not.toBeNull();
    expect(attached[1].anchor).toBeNull();
  });
});

describe('evidenceBadge — VERIFIED만 검증 표시', () => {
  const ALL: EvidenceDisplayStatus[] = [
    'VERIFIED', 'UNVERIFIED_PAGE_MISMATCH', 'UNVERIFIED_VALUE_MISMATCH', 'UNVERIFIED_INFERRED',
    'UNVERIFIED_PARTIAL', 'UNVERIFIED_AMBIGUOUS', 'UNVERIFIED_NOT_FOUND', 'UNVERIFIED_NO_QUOTE',
    'UNVERIFIED_NO_TEXT_LAYER', 'UNVERIFIED_STALE_SOURCE', 'UNVERIFIED_ERROR', 'UNVERIFIED_NOT_RUN',
  ];

  it('모든 상태가 비어 있지 않은 라벨을 가진다 (색만으로 구분하지 않는다)', () => {
    for (const status of ALL) {
      expect(evidenceBadge(status).label.length).toBeGreaterThan(0);
    }
  });

  it('VERIFIED 외에는 verified=false다', () => {
    expect(evidenceBadge('VERIFIED').verified).toBe(true);
    for (const status of ALL.filter((s) => s !== 'VERIFIED')) {
      expect(evidenceBadge(status).verified).toBe(false);
    }
  });

  it('부분 일치는 성공 톤을 쓰지 않는다', () => {
    expect(evidenceBadge('UNVERIFIED_PARTIAL').tone).not.toBe('success');
  });
});

describe('evidenceTarget — 확인 페이지와 후보 페이지를 구분한다', () => {
  it('확인된 페이지를 우선한다', () => {
    expect(evidenceTarget(anchor())).toEqual({ page: 4, confirmed: true });
  });

  it('page_mismatch는 이동은 가능하지만 confirmed가 아니다', () => {
    const target = evidenceTarget(anchor({ display_status: 'UNVERIFIED_PAGE_MISMATCH', matched_page: 7 }));
    expect(target).toEqual({ page: 7, confirmed: false });
  });

  it('확인 페이지가 없으면 LLM 주장 페이지를 후보로 준다', () => {
    const target = evidenceTarget(anchor({ display_status: 'UNVERIFIED_NOT_FOUND', matched_page: null }));
    expect(target).toEqual({ page: 4, confirmed: false });
  });

  it('페이지가 전혀 없으면 null이다', () => {
    expect(evidenceTarget(anchor({ matched_page: null, claimed_page: null }))).toBeNull();
    expect(evidenceTarget(null)).toBeNull();
  });
});

describe('evidenceTooltip — 확인된 인용과 주장된 인용을 라벨로 구분한다', () => {
  it('VERIFIED는 확인된 원문을 보여준다', () => {
    const text = evidenceTooltip(anchor());
    expect(text).toContain('확인된 원문');
    expect(text).toContain('wave-\nlength of 1550 nm');
  });

  it('미확인은 "LLM이 주장한 인용"으로 명시한다', () => {
    const text = evidenceTooltip(anchor({ display_status: 'UNVERIFIED_NOT_FOUND', matched_quote: null }));
    expect(text).toContain('LLM이 주장한 인용');
    expect(text).not.toContain('확인된 원문');
  });

  it('앵커가 없으면 검증 미실행을 알린다', () => {
    expect(evidenceTooltip(null)).toContain('검증 미실행');
  });
});
