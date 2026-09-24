import { describe, expect, it } from 'vitest';
import { buildDeepDiveNarrative, findSectionAnswerIndex, getSummaryDisplayStatus, readInputCoverage, readSummaryExtensions } from './summaryContent';
import type { AnalysisStatus } from './api';

describe('readInputCoverage', () => {
  const partial = { mode: 'text', status: 'partial', missing: ['수식 판독 미확인'], pdf_sha256: null };
  const pdf = { mode: 'pdf', status: 'provided_pdf', missing: [], pdf_sha256: 'a'.repeat(64) };

  it('keeps text-only input visibly partial', () => {
    // Given a text-only input with an explicit missing range.
    const data = { _input_coverage: partial };
    // When reading its coverage.
    const result = readInputCoverage(data);
    // Then keep the missing range without implying complete input.
    expect(result).toEqual({ kind: 'partial', missing: ['수식 판독 미확인'] });
  });

  it('keeps partial input partial when the precise missing range is unknown', () => {
    // Given partial input with no known range description.
    const data = { _input_coverage: { ...partial, missing: [] } };
    // When reading its coverage.
    const result = readInputCoverage(data);
    // Then do not upgrade it to complete input.
    expect(result).toEqual({ kind: 'partial', missing: [] });
  });

  it('preserves known PDF input omissions without claiming verified analysis', () => {
    // Given an original PDF with a known missing supplement.
    const data = { _input_coverage: { ...pdf, missing: ['보충자료 미제공'] } };
    // When reading its coverage.
    const result = readInputCoverage(data);
    // Then report the provided input and retain its limitations.
    expect(result).toEqual({ kind: 'provided_pdf', missing: ['보충자료 미제공'] });
  });

  it('keeps absent metadata legacy rather than assuming full input', () => {
    // Given a stored result from before coverage metadata existed.
    const data = { detailed_analysis: '구형 본문' };
    // When reading its coverage.
    const result = readInputCoverage(data);
    // Then the input scope remains unconfirmed.
    expect(result).toEqual({ kind: 'legacy' });
  });

  it.each([
    undefined, null, [], {},
    { ...partial, status: 'full_pdf' },
    { ...partial, mode: 'unknown' },
    { ...partial, missing: undefined },
    { ...partial, missing: [''] },
    { ...partial, missing: ['  '] },
    { ...partial, missing: ['수식 판독 미확인', 3] },
    { ...partial, pdf_sha256: undefined },
    { ...partial, pdf_sha256: 'a'.repeat(64) },
    { ...pdf, mode: 'text' },
    { ...pdf, pdf_sha256: null },
    { ...pdf, pdf_sha256: 'not-a-hash' },
  ])('keeps malformed new metadata unknown: %j', (coverage) => {
    // Given metadata that is present but violates the storage contract.
    const data = { _input_coverage: coverage };
    // When reading its coverage.
    const result = readInputCoverage(data);
    // Then do not downgrade malformed metadata to legacy or successful input.
    expect(result).toEqual({ kind: 'unknown' });
  });
});

it('keeps failed generation envelopes distinct from legacy successful data', () => {
  expect(readSummaryExtensions({ _raw: 'broken JSON', _parse_error: 'invalid JSON' }).kind).toBe('invalid');
});

it('preserves the stored explanation when the deep dive was skipped', () => {
  expect(buildDeepDiveNarrative({ skipped: true, message: '이 논문에서는 심층 분석을 건너뛰었어요.' }).main)
    .toContain('이 논문에서는 심층 분석을 건너뛰었어요.');
});

const answer = {
  section_title: '2. Methods', question: '무엇을 했나요?', answer: '검증용 답변',
  explanation: '', source_refs: ['2. Methods'],
};
const check = {
  item: '실험 대상', paper_condition: '검증용 조건', condition_basis: 'reported',
  check_before_transfer: '대상을 확인해요.', source_refs: ['2. Methods'],
};

describe('summary extension boundary', () => {
  it('separates legacy data, missing fields, and valid empty arrays', () => {
    expect(readSummaryExtensions({ detailed_analysis: '이전 분석' })).toEqual({ kind: 'legacy' });
    expect(readSummaryExtensions({ section_answers: [] }).kind).toBe('invalid');
    expect(readSummaryExtensions({ transfer_checks: [] }).kind).toBe('invalid');
    expect(readSummaryExtensions({ section_answers: [], transfer_checks: [] })).toEqual({
      kind: 'current', sectionAnswers: [], transferChecks: [],
    });
  });

  it.each([
    { section_answers: null, transfer_checks: [] },
    { section_answers: {}, transfer_checks: [] },
    { section_answers: [null], transfer_checks: [] },
    { section_answers: [{ ...answer, answer: 3 }], transfer_checks: [] },
    { section_answers: [{ ...answer, question: '  ' }], transfer_checks: [] },
    { section_answers: [{ ...answer, explanation: undefined }], transfer_checks: [] },
    { section_answers: [{ ...answer, source_refs: [] }], transfer_checks: [] },
    { section_answers: [{ ...answer, source_refs: [''] }], transfer_checks: [] },
    { section_answers: [{ ...answer, source_refs: ['1', '2', '3', '4', '5'] }], transfer_checks: [] },
    { section_answers: Array.from({ length: 13 }, () => answer), transfer_checks: [] },
    { section_answers: [], transfer_checks: [{ ...check, condition_basis: 'verified' }] },
    { section_answers: [], transfer_checks: [{ ...check, source_refs: [] }] },
    { section_answers: [], transfer_checks: [{ ...check, condition_basis: 'inferred', source_refs: [] }] },
    { section_answers: [], transfer_checks: [{ ...check, check_before_transfer: false }] },
    { section_answers: [], transfer_checks: Array.from({ length: 9 }, () => check) },
  ])('rejects malformed entries without dropping them', (data) => {
    expect(readSummaryExtensions(data).kind).toBe('invalid');
  });

  it('accepts all evidence bases and the documented limits', () => {
    const result = readSummaryExtensions({
      section_answers: Array.from({ length: 12 }, () => answer),
      transfer_checks: [check, { ...check, condition_basis: 'inferred' },
        ...Array.from({ length: 6 }, () => ({ ...check, condition_basis: 'not_reported', source_refs: [] }))],
    });
    expect(result.kind).toBe('current');
  });
});

it('matches one title after NFC, whitespace and case normalization only', () => {
  expect(findSectionAnswerIndex(' 2.  METHODS ', [answer])).toBe(0);
  expect(findSectionAnswerIndex('2. Methods', [answer, answer])).toBeNull();
  expect(findSectionAnswerIndex('3. Methods', [answer])).toBeNull();
  expect(findSectionAnswerIndex('2 Methods', [answer])).toBeNull();
  expect(findSectionAnswerIndex('II. Methods', [answer])).toBeNull();
  expect(findSectionAnswerIndex('2. 방법', [answer])).toBeNull();
  expect(findSectionAnswerIndex('서론'.normalize('NFD'), [{ ...answer, section_title: '서론' }])).toBe(0);
});

it('keeps the six fields and limitations in main and all other evaluations in additional', () => {
  const narrative = buildDeepDiveNarrative({
    problem_definition: '문제 본문', as_is: '기존 본문', to_be: '목표 본문', solution: '원리 본문',
    method_summary: '방법 본문', key_results: '결과 2 Hz', weaknesses: ['원문의 한계'],
    novelty_assessment: '신규성 본문', comparison_to_prior_work: '비교 본문', comparison_scope: 'in_paper_only',
    strengths: ['강점 본문'], suggested_improvements: ['제안 본문'], practical_applications: ['응용 본문'],
    follow_up_questions: ['후속 본문'],
  });
  expect(narrative.main).toBe('### 문제\n\n문제 본문\n\n### 기존 접근\n\n기존 본문\n\n### 목표\n\n목표 본문\n\n### 해결 원리\n\n원리 본문\n\n### 방법\n\n방법 본문\n\n### 결과\n\n결과 2 Hz\n\n### 해석의 한계\n\n- 원문의 한계');
  for (const value of ['신규성 본문', '비교 본문', '강점 본문', '제안 본문', '응용 본문', '후속 본문', '외부 문헌 검증']) {
    expect(narrative.additional).toContain(value);
    expect(narrative.main).not.toContain(value);
  }
  expect(narrative.additional).not.toContain('원문의 한계');
});

it('omits empty optional fields and preserves legacy detailed_analysis', () => {
  expect(buildDeepDiveNarrative({ as_is: ' ', to_be: '', detailed_analysis: '기존 장문\n\n둘째 문단' })).toEqual({
    main: '기존 장문\n\n둘째 문단', additional: '',
  });
});

it('shows invalid stored extensions as an error while preserving active generation status', () => {
  const status: AnalysisStatus = {
    paper_id: 1, overall_status: 'completed', progress_pct: 100, current_phase: null,
    total_cost_usd: 0, total_tokens_in: 0, total_tokens_out: 0,
    phases: [{
      phase: 'deep_dive', status: 'completed', started_at: null, completed_at: null,
      model_used: null, tokens_in: null, tokens_out: null, cost_usd: null, error_message: null,
    }],
  };
  expect(getSummaryDisplayStatus(status, { detailed_analysis: '구형 결과' })).toBe(status);
  expect(getSummaryDisplayStatus(status, { section_answers: [], transfer_checks: [] })).toBe(status);
  expect(getSummaryDisplayStatus(status, { section_answers: [] })).toMatchObject({
    overall_status: 'error', phases: [{ phase: 'deep_dive', status: 'error' }],
  });
  const running: AnalysisStatus = {
    ...status, overall_status: 'running',
    phases: status.phases.map((phase) => ({ ...phase, status: 'running' })),
  };
  expect(getSummaryDisplayStatus(running, { section_answers: [] })).toEqual(running);
  expect(getSummaryDisplayStatus(null, { section_answers: [] })).toBeNull();
});

it('marks a skipped deep dive neutrally without changing active stages', () => {
  const status: AnalysisStatus = {
    paper_id: 1, overall_status: 'completed', progress_pct: 100, current_phase: null,
    total_cost_usd: 0, total_tokens_in: 0, total_tokens_out: 0,
    phases: [{ phase: 'deep_dive', status: 'completed', started_at: null, completed_at: null,
      model_used: 'system', tokens_in: 0, tokens_out: 0, cost_usd: 0, error_message: null }],
  };
  expect(getSummaryDisplayStatus(status, { skipped: true, message: '건너뛰었어요' })?.phases[0].status)
    .toBe('skipped');
  expect(getSummaryDisplayStatus({ ...status, phases: [{ ...status.phases[0], status: 'running' }] },
    { skipped: true })?.phases[0].status).toBe('running');
});
