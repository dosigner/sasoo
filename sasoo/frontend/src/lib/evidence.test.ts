import { afterEach, describe, expect, it, vi } from 'vitest';
import type { EvidenceAnchor, EvidenceDisplayStatus, RecipeEvidence } from '@/lib/api';
import {
  attachEvidence,
  evidenceBadge,
  evidenceSummaryTone,
  evidenceTarget,
  evidenceTooltip,
  parseRecipeParameters,
  resolveDisplayStatus,
  summarizeAnchoredEvidence,
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

  describe('label 불일치 경고', () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('불일치를 조용히 숨기지 않고 콘솔에 남긴다 (드리프트 탐지용)', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const rows = parseRecipeParameters([{ name: 'laser_power', value: '3.2' }]);
      attachEvidence(rows, evidence([anchor()]));
      expect(warn).toHaveBeenCalledTimes(1);
      expect(warn).toHaveBeenCalledWith(
        '[evidence] anchor label mismatch — hiding anchor',
        expect.objectContaining({ index: 0, expected: 'laser_power', got: 'wavelength' }),
      );
    });

    it('label이 일치하면 경고하지 않는다', () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const rows = parseRecipeParameters([{ name: 'wavelength', value: '1550' }]);
      attachEvidence(rows, evidence([anchor()]));
      expect(warn).not.toHaveBeenCalled();
    });
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

  it('PAGE_MISMATCH 배지는 "확인"이 아니라 "발견"이라고 쓴다 (DEC-012)', () => {
    // "다른 페이지에서 확인"은 검증 도장으로 읽힌다. 확인한 것은 위치가 아니라 존재다.
    expect(evidenceBadge('UNVERIFIED_PAGE_MISMATCH').label).toBe('다른 페이지에서 발견');
  });
});

describe('summarizeAnchoredEvidence / evidenceSummaryTone — 배지는 화면 실제 결과로 센다 (I-2)', () => {
  it('전부 VERIFIED면 total과 verified가 같다', () => {
    const rows = parseRecipeParameters([{ name: 'wavelength', value: '1550' }]);
    const attached = attachEvidence(rows, evidence([anchor()]));
    expect(summarizeAnchoredEvidence(attached)).toEqual({ verified: 1, total: 1 });
  });

  it('fail-closed로 숨겨진 앵커는 미검증으로 잡히고 total에는 남는다', () => {
    // 라벨 불일치로 앵커가 숨겨져도 그 파라미터 행 자체는 여전히 화면에 남는다 —
    // 분모(total)는 유지하고 분자(verified)만 0으로 세야 배지와 표가 일치한다.
    const rows = parseRecipeParameters([{ name: 'laser_power', value: '3.2' }]);
    const attached = attachEvidence(rows, evidence([anchor()]));
    expect(summarizeAnchoredEvidence(attached)).toEqual({ verified: 0, total: 1 });
  });

  it('일부만 VERIFIED면 verified < total이다', () => {
    const rows = parseRecipeParameters([
      { name: 'wavelength', value: '1550' },
      { name: 'power', value: '3.2' },
    ]);
    const attached = attachEvidence(
      rows,
      evidence([anchor(), anchor({ target_index: 1, target_label: 'power', display_status: 'UNVERIFIED_NOT_FOUND' })]),
    );
    expect(summarizeAnchoredEvidence(attached)).toEqual({ verified: 1, total: 2 });
  });

  it('evidenceSummaryTone: 전부 검증돼야만 success다 (1/N은 warning)', () => {
    expect(evidenceSummaryTone(1, 1)).toBe('success');
    expect(evidenceSummaryTone(1, 20)).toBe('warning');
    expect(evidenceSummaryTone(0, 5)).toBe('neutral');
    expect(evidenceSummaryTone(0, 0)).toBe('neutral');
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

  it('검증 방법은 CSV와 같은 헬퍼로 적고, 모르는 코드도 조용히 버리지 않는다', () => {
    expect(evidenceTooltip(anchor())).toContain('표기 정규화 일치');
    expect(evidenceTooltip(anchor({ match_method: 'future_method' }))).toContain('future_method');
  });

  // DEC-012 — 페이지만 어긋난 near-miss는 "인용이 원문에 축자로 있다"가 보장되는 유일한
  // 미검증 버킷이다. 검증 도장 없이 문구로만 노출한다.
  it('PAGE_MISMATCH는 발견된 원문을 발견 페이지와 함께 보여준다', () => {
    const text = evidenceTooltip(
      anchor({
        display_status: 'UNVERIFIED_PAGE_MISMATCH',
        matched_page: 7,
        matched_quote: 'a wavelength of 1550 nm',
      }),
    );
    expect(text).toContain('발견된 원문 (p.7)');
    expect(text).toContain('a wavelength of 1550 nm');
  });

  it('PAGE_MISMATCH는 주장 페이지를 함께 적고 검증 문구는 쓰지 않는다', () => {
    const text = evidenceTooltip(
      anchor({ display_status: 'UNVERIFIED_PAGE_MISMATCH', matched_page: 7 }),
    );
    expect(text).toContain('LLM 주장 p.4');
    expect(text).not.toContain('확인된 원문');
    // 같은 페이지 번호를 "발견된 원문 (p.7)"과 "후보 위치 p.7"로 두 번 적지 않는다.
    expect(text).not.toContain('후보 위치');
  });

  it('PAGE_MISMATCH 외 미검증 상태는 matched_quote를 노출하지 않는다', () => {
    // partial은 위조 인용 81%가 통과한 실측이 있다 — 어떤 표면에서도 원문처럼 보이면 안 된다.
    const hidden: EvidenceDisplayStatus[] = [
      'UNVERIFIED_PARTIAL',
      'UNVERIFIED_AMBIGUOUS',
      'UNVERIFIED_VALUE_MISMATCH',
      'UNVERIFIED_INFERRED',
      'UNVERIFIED_STALE_SOURCE',
    ];
    for (const status of hidden) {
      const text = evidenceTooltip(
        anchor({ display_status: status, matched_quote: '위조된 원문 조각', matched_page: 9 }),
      );
      expect(text).not.toContain('위조된 원문 조각');
      expect(text).not.toContain('발견된 원문');
    }
  });
});
