// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { DeepDiveSummary } from './DeepDiveSummary';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

const data = {
  problem_definition: '검증용 문제', key_results: '검증용 결과 2 Hz', weaknesses: ['해석의 한계 본문'],
  strengths: ['추가 강점 본문'],
  section_answers: [{
    section_title: '2. Methods', question: '어떤 조건을 썼나요?', answer: '검증용 짧은 답',
    explanation: '검증용 자세한 설명', source_refs: ['2. Methods', 'Fig. 2', 'Fig. 9', 'p.12'],
  }],
  transfer_checks: [
    { item: '대상', paper_condition: '원문 조건', condition_basis: 'reported', check_before_transfer: '대상 비교 제안', source_refs: ['Fig. 2'] },
    { item: '가정', paper_condition: '추론 조건', condition_basis: 'inferred', check_before_transfer: '가정 비교 제안', source_refs: ['2. Methods'] },
    { item: '보정', paper_condition: '보정 정보가 제공되지 않았어요.', condition_basis: 'not_reported', check_before_transfer: '보정 확인 제안', source_refs: [] },
  ],
};

const partialData = {
  ...data,
  _input_coverage: { mode: 'text', status: 'partial', missing: ['수식과 그림 판독 미확인'], pdf_sha256: null },
};

function render(payload: Record<string, unknown> = data) {
  const container = document.createElement('div');
  container.dataset.analysisScroll = '';
  document.body.appendChild(container);
  const currentRoot = createRoot(container);
  root = currentRoot;
  const onClick = vi.fn();
  act(() => currentRoot.render(<DeepDiveSummary data={payload} citations={{
    onClick, isAllowed: (target) => target.type === 'page' || (target.type === 'figure' && target.n === 2),
  }} />));
  return { container, onClick };
}

describe('DeepDiveSummary', () => {
  it('shows the partial-input warning and missing range before the summary body', () => {
    // Given an analysis generated from text-only input.
    const payload = partialData;
    // When displaying the summary.
    const { container } = render(payload);
    // Then the limitation is visible before the body without opening details.
    const notice = container.querySelector('[data-summary-coverage="partial"]');
    const main = container.querySelector('[data-summary-anchor="main"]');
    expect(notice?.getAttribute('role')).toBe('alert');
    expect(notice?.textContent).toContain('부분 분석');
    expect(notice?.textContent).toContain('수식과 그림 판독 미확인');
    expect(notice?.closest('details')).toBeNull();
    expect(main && notice?.compareDocumentPosition(main)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('reports unknown omission details without removing the partial warning', () => {
    // Given partial metadata without a precise omission description.
    const payload = { ...partialData, _input_coverage: { ...partialData._input_coverage, missing: [] } };
    // When displaying the summary.
    const { container } = render(payload);
    // Then the user sees the remaining uncertainty.
    expect(container.querySelector('[data-summary-coverage="partial"]')?.textContent)
      .toContain('구체적인 누락 범위는 확인되지 않았어요.');
  });

  it('shows provided PDF input as an input fact and preserves known omissions', () => {
    // Given a PDF input with an unavailable supplement.
    const payload = { ...data, _input_coverage: {
      mode: 'pdf', status: 'provided_pdf', missing: ['보충자료 미제공'], pdf_sha256: 'a'.repeat(64),
    } };
    // When displaying the summary.
    const { container } = render(payload);
    // Then input provision is not presented as a correctness guarantee.
    const notice = container.querySelector('[data-summary-coverage="provided_pdf"]');
    expect(notice?.textContent).toContain('원본 PDF를 입력으로 제공했어요.');
    expect(notice?.textContent).toContain('모든 내용을 정확히 판독했다는 뜻은 아니에요.');
    expect(notice?.textContent).toContain('보충자료 미제공');
    expect(notice?.textContent).not.toContain('전체 분석 완료');
  });

  it.each([
    ['legacy', { detailed_analysis: '구형 본문' }, '이전에 생성한 결과라 원문 입력 범위를 확인할 수 없어요.'],
    ['unknown', { ...data, _input_coverage: { status: 'provided_pdf' } }, '입력 범위 정보가 올바르지 않아 분석 범위가 불명확해요.'],
  ])('keeps %s coverage visibly unconfirmed', (kind, payload, message) => {
    // Given legacy or malformed coverage metadata.
    // When displaying the summary.
    const { container } = render(payload);
    // Then neither case implies complete analysis.
    const notice = container.querySelector(`[data-summary-coverage="${kind}"]`);
    expect(notice?.textContent).toContain('입력 범위 미확인');
    expect(notice?.textContent).toContain(message);
    expect(notice?.textContent).not.toContain('원본 PDF를 입력으로 제공했어요.');
  });

  it('keeps questions, short answers, limitations and transfer conditions outside closed details', () => {
    const { container } = render(partialData);
    const answer = container.querySelector('[data-summary-answer="0"]');
    expect(answer?.textContent).toContain('검증용 짧은 답');
    expect(answer?.querySelector('details')?.open).toBe(false);
    expect(answer?.querySelector('details')?.textContent).not.toContain('검증용 짧은 답');
    expect(container.querySelector('[data-summary-anchor="main"]')?.textContent).toContain('해석의 한계 본문');
    for (const label of ['원문에 명시', '원문에서 추론', '제공 자료에서 확인 못함', '확인할 점 (적용 전 제안)']) {
      expect(container.textContent).toContain(label);
    }
    expect(container.textContent).not.toContain('적용 가능');
    expect(container.querySelector('details[data-summary-additional]')?.hasAttribute('open')).toBe(false);
    expect(container.querySelector('details[data-summary-additional]')?.textContent).toContain('추가 강점 본문');
  });

  it('uses allowed figure and table citations only for new source references', () => {
    const { container, onClick } = render();
    const answer = container.querySelector('[data-summary-answer="0"]');
    const chips = answer?.querySelectorAll<HTMLButtonElement>('.citation-chip');
    expect(Array.from(chips ?? []).map((chip) => chip.textContent)).toEqual(['Fig. 2']);
    act(() => chips?.[0]?.click());
    expect(onClick).toHaveBeenCalledWith({ type: 'figure', n: 2 });
    expect(answer?.textContent).toContain('Fig. 9');
    expect(answer?.textContent).toContain('p.12');
    expect(answer?.querySelector('[data-summary-sources]')?.textContent).toContain('2. Methods');
    expect(answer?.querySelector('[data-summary-sources] ol')).toBeNull();
  });

  it('keeps unavailable supplement references as complete plain text instead of linking a main figure', () => {
    const refs = ['2. Methods', 'Fig. 2', 'Figure 2—figure supplement 1', 'Supplementary Figure 2'];
    const { container } = render({
      ...data,
      section_answers: [{ ...data.section_answers[0], source_refs: refs }],
      transfer_checks: [{ ...data.transfer_checks[0], source_refs: refs }],
    });
    for (const sources of container.querySelectorAll('[data-summary-sources]')) {
      expect([...sources.querySelectorAll('.citation-chip')].map((chip) => chip.textContent)).toEqual(['Fig. 2']);
      expect(sources.textContent).toContain(refs.join(', '));
    }
  });

  it('distinguishes valid empty results, legacy results and invalid stored results', () => {
    const { container } = render({ detailed_analysis: '구형 본문' });
    expect(container.textContent).toContain('구형 본문');
    expect(container.textContent).toContain('이전에 생성한 분석이에요.');
    expect(container.textContent).not.toContain('이번 분석에서 작성된 항목이 없어요.');
    act(() => root?.render(<DeepDiveSummary data={{ section_answers: [], transfer_checks: [] }} />));
    expect(container.querySelectorAll('[data-summary-empty]').length).toBe(2);
    act(() => root?.render(<DeepDiveSummary data={{ section_answers: [] }} />));
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('형식이 올바르지 않아요');
    expect(container.querySelector('[data-summary-empty]')).toBeNull();
  });

  it('scopes document links and focuses their destination without motion', () => {
    const request = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
    const { container } = render(partialData);
    const scrollTo = vi.fn();
    Object.defineProperty(container, 'scrollTo', { configurable: true, value: scrollTo });
    const heading = container.querySelector<HTMLElement>('[data-summary-anchor="answers"]');
    if (!heading) throw new Error('Answers heading not found');
    vi.spyOn(container, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 240, 560, 660));
    vi.spyOn(heading, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 840, 520, 26));
    const link = container.querySelector<HTMLButtonElement>('button[data-summary-link="answers"]');
    act(() => link?.click());
    expect(scrollTo).toHaveBeenCalledWith({ behavior: 'auto', top: 600 });
    expect(document.activeElement).toBe(container.querySelector('[data-summary-anchor="answers"]'));
    expect(request).not.toHaveBeenCalled();
  });

  it('tracks the current summary section in the panel scroll', () => {
    const { container } = render();
    const main = container.querySelector<HTMLElement>('[data-summary-anchor="main"]');
    const answers = container.querySelector<HTMLElement>('[data-summary-anchor="answers"]');
    const transfer = container.querySelector<HTMLElement>('[data-summary-anchor="transfer"]');
    if (!main || !answers || !transfer) throw new Error('Summary headings not found');
    vi.spyOn(main, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, -100, 500, 20));
    vi.spyOn(answers, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 4, 500, 20));
    vi.spyOn(transfer, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 300, 500, 20));
    act(() => container.dispatchEvent(new Event('scroll')));
    expect(container.querySelector('[data-summary-link="answers"]')?.getAttribute('aria-current')).toBe('location');
    expect(container.querySelector('[data-summary-link="transfer"]')?.getAttribute('aria-current')).toBeNull();
    vi.spyOn(transfer, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 5, 500, 20));
    act(() => container.dispatchEvent(new Event('scroll')));
    expect(container.querySelector('[data-summary-link="transfer"]')?.getAttribute('aria-current')).toBe('location');
  });
});
