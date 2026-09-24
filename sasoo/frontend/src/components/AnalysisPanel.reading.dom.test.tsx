// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { AnalysisResults, AnalysisStatus, ArtifactStatus, FigureListResponse, TableListResponse } from '@/lib/api';
import type { CitationTarget } from '@/lib/citations';
import AnalysisPanel, { type CitationFocus } from './AnalysisPanel';

const { chatWithAgent, getGuide } = vi.hoisted(() => ({ chatWithAgent: vi.fn(), getGuide: vi.fn() }));
vi.mock('@/lib/api', () => ({ chatWithAgent }));
vi.mock('@/lib/guideCache', () => ({ getGuide, setGuide: vi.fn() }));
vi.mock('./FigureGallery', () => ({ default: () => <div data-citation-anchor="figure-1">검증용 그림 목록</div> }));
vi.mock('./TableGallery', () => ({ default: () => null }));
vi.mock('./RecipeCard', () => ({ default: () => null }));
vi.mock('./ExperimentPlanTab', () => ({ default: () => null }));
vi.mock('./ReportExport', () => ({ default: () => null }));
vi.mock('./synthesis/SynthesisView', () => ({ SynthesisView: () => null }));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;
const frames = new Map<number, FrameRequestCallback>();
const scrollIntoView = vi.fn();
const scrollTo = vi.fn(function (this: HTMLElement, options: ScrollToOptions) {
  this.scrollTop = options.top ?? this.scrollTop;
});
let nextFrame = 0;

beforeEach(() => {
  getGuide.mockResolvedValue({
    markdown: '## 섹션별 직관\n### 2. Methods (p.4)\n방법의 직관\n### 3. Results\n결과의 직관',
    createdAt: 1, level: null, costUsd: 0,
  });
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    const id = ++nextFrame;
    frames.set(id, callback);
    return id;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: scrollIntoView });
  Object.defineProperty(HTMLElement.prototype, 'scrollTo', { configurable: true, value: scrollTo });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
  frames.clear();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
});

const answer = {
  section_title: '2. Methods', question: '무엇을 했나요?', answer: '검증용 짧은 답',
  explanation: '추가 설명', source_refs: ['2. Methods'],
};
const data = { problem_definition: '검증용 문제', section_answers: [answer], transfer_checks: [] };
const status: AnalysisStatus = {
  paper_id: 1, overall_status: 'completed', progress_pct: 100, current_phase: null,
  total_cost_usd: 0, total_tokens_in: 0, total_tokens_out: 0,
  phases: (['screening', 'citation', 'visual', 'recipe', 'deep_dive'] as const).map((phase) => ({
    phase, status: 'completed', started_at: null, completed_at: null, model_used: null,
    tokens_in: null, tokens_out: null, cost_usd: null, error_message: null,
  })),
};

function panel(
  payload: Record<string, unknown> = data,
  paperId = '1',
  citationFocus: CitationFocus | null = null,
  onCitationClick?: (target: CitationTarget) => void,
  options: { status?: AnalysisStatus; figures?: FigureListResponse; tables?: TableListResponse;
    artifactStatus?: ArtifactStatus; terminalState?: 'cancelled' } = {},
) {
  const currentStatus = options.status ?? status;
  const results: AnalysisResults = {
    paper_id: Number(paperId), status: currentStatus, screening: { summary: '스크리닝 본문' },
    citation: { total_references: 1, summary: '인용 본문\n\n### First source\n\n첫 근거\n\n### Second source\n\n둘째 근거' },
    visual: null, recipe: null, deep_dive: payload,
  };
  return <AnalysisPanel status={currentStatus} results={results} paperId={paperId} figures={options.figures ?? null}
    tables={options.tables ?? null} recipe={null} mermaid={null} visualizations={null} isRunning={false}
    citationFocus={citationFocus} onCitationClick={onCitationClick}
    artifactStatus={options.artifactStatus} terminalState={options.terminalState} />;
}

async function render(payload: Record<string, unknown> = data, options: Parameters<typeof panel>[4] = {}) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const currentRoot = createRoot(container);
  root = currentRoot;
  await act(async () => currentRoot.render(panel(payload, '1', null, undefined, options)));
  await flushFrames();
  return container;
}

async function flushFrames() {
  await act(async () => {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback(0));
  });
}

function button(container: HTMLElement, text: string): HTMLButtonElement {
  const result = [...container.querySelectorAll('button')].find((element) => element.textContent === text);
  if (!result) throw new Error(`Button not found: ${text}`);
  return result;
}

function phase(container: HTMLElement, name: string): HTMLButtonElement {
  const result = container.querySelector<HTMLButtonElement>(`[data-phase="${name}"] > button`);
  if (!result) throw new Error(`Phase not found: ${name}`);
  return result;
}

describe('AnalysisPanel summary reading', () => {
  it('shows a single compact status for a complete analysis', async () => {
    const container = await render();
    expect(container.querySelector('[data-status-compact]')?.textContent).toContain('완료 5');
    expect(container.textContent).not.toContain('준비한 결과를 순서대로 검토하세요.');
    expect(container.querySelector('[data-summary-panel]')?.textContent).toContain('스크리닝 본문');
  });

  it('keeps skipped phase reasons available in the compact status', async () => {
    const skipped: AnalysisStatus = {
      ...status,
      phases: status.phases.map((phase) => phase.phase === 'recipe'
        ? { ...phase, status: 'skipped', error_message: '원문에 재현 조건 없음' } : phase),
    };
    const container = await render(data, { status: skipped });
    expect(container.querySelector('[data-status-compact]')?.textContent).toContain('완료 4, 건너뜀 1');
    expect(container.querySelector('[data-status-compact] details')?.textContent).toContain('원문에 재현 조건 없음');
    expect(container.querySelector('[data-summary-panel]')?.textContent).not.toContain('레시피 (건너뜀)');
  });

  it.each([
    ['running', { ...status, overall_status: 'running' }, data, undefined, undefined],
    ['error', { ...status, overall_status: 'error' }, data, undefined, undefined],
    ['cancelled', status, data, undefined, 'cancelled' as const],
    ['partial input', status, { ...data, _input_coverage: { mode: 'text', status: 'partial', missing: [], pdf_sha256: null } }, undefined, undefined],
    ['invalid result', status, { ...data, transfer_checks: null }, undefined, undefined],
    ['partial visual', status, data, { text_ready: true, visual_ready: false, visual_state: 'partial' } satisfies ArtifactStatus, undefined],
  ])('keeps detailed status for %s', async (_label, currentStatus, payload, artifactStatus, terminalState) => {
    const container = await render(payload, { status: currentStatus, artifactStatus, terminalState });
    expect(container.querySelector('[data-status-compact]')).toBeNull();
    expect(container.textContent).toContain('분석 상태');
  });

  it('returns from a summary figure citation to the saved reading position', async () => {
    const figures: FigureListResponse = {
      figures: [{ id: 1, paper_id: 1, figure_num: 'Figure 1', page_number: 3,
        caption: '검증 그림', file_path: null, ai_analysis: null, quality: null, detailed_explanation: null }],
      total: 1, visual_state: 'ready', artifacts_ready: true,
    };
    const payload = { ...data, section_answers: [{ ...answer, source_refs: ['Fig. 1'] }] };
    const onCitationClick = vi.fn();
    const container = await render(payload, { figures });
    await act(async () => root?.render(panel(payload, '1', null, onCitationClick, { figures })));
    const scroller = container.querySelector<HTMLElement>('[data-analysis-scroll]');
    if (!scroller) throw new Error('Reading panel not found');
    scroller.scrollTop = 900;
    act(() => scroller.dispatchEvent(new Event('scroll')));
    act(() => container.querySelector<HTMLButtonElement>('[data-summary-answer] summary')?.click());
    act(() => container.querySelector<HTMLButtonElement>('[data-summary-answer] .citation-chip')?.click());
    expect(onCitationClick).toHaveBeenCalledWith({ type: 'figure', n: 1 });
    await act(async () => root?.render(panel(payload, '1', { tab: 'figures', anchor: 'figure-1', token: 1 }, onCitationClick, { figures })));
    expect(button(container, '요약으로 돌아가기')).toBeTruthy();
    scroller.scrollTop = 100;
    act(() => button(container, '요약으로 돌아가기').click());
    await flushFrames();
    expect(scroller.scrollTop).toBe(900);
    expect(container.querySelector('[data-summary-answer]')?.textContent).toContain('검증용 짧은 답');
  });

  it('does not offer a summary return for a chat citation', async () => {
    const container = await render();
    await act(async () => root?.render(panel(data, '1', { tab: 'figures', anchor: 'figure-1', token: 1 })));
    expect(container.textContent).not.toContain('요약으로 돌아가기');
  });

  it('returns from an available table reference without exposing an unavailable reference', async () => {
    const tables: TableListResponse = {
      tables: [{ id: 1, paper_id: 1, table_num: 'Table 1', caption: '검증 표' }],
      total: 1, visual_state: 'ready', artifacts_ready: true,
    };
    const payload = { ...data, section_answers: [{ ...answer, source_refs: ['Table 1', 'Table 9'] }] };
    const onCitationClick = vi.fn();
    const container = await render(payload, { tables });
    await act(async () => root?.render(panel(payload, '1', null, onCitationClick, { tables })));
    const chips = container.querySelectorAll<HTMLButtonElement>('[data-summary-answer] .citation-chip');
    expect([...chips].map((chip) => chip.textContent)).toEqual(['Table 1']);
    act(() => container.querySelector<HTMLButtonElement>('[data-summary-answer] summary')?.click());
    act(() => chips[0]?.click());
    await act(async () => root?.render(panel(payload, '1', { tab: 'tables', anchor: 'table-1', token: 1 }, onCitationClick, { tables })));
    expect(button(container, '요약으로 돌아가기')).toBeTruthy();
    act(() => button(container, '요약으로 돌아가기').click());
    await flushFrames();
    expect(container.querySelector('[data-summary-answer]')?.textContent).toContain('검증용 짧은 답');
  });
  it('defaults to open screening/deep dive and closed citation, preserving user changes across tabs', async () => {
    const container = await render();
    expect([...container.querySelectorAll('[data-phase]')].map((node) => node.getAttribute('data-phase')))
      .toEqual(['screening', 'deep_dive', 'citation']);
    expect(phase(container, 'screening').getAttribute('aria-expanded')).toBe('true');
    expect(phase(container, 'deep_dive').getAttribute('aria-expanded')).toBe('true');
    expect(phase(container, 'citation').getAttribute('aria-expanded')).toBe('false');
    const details = container.querySelector<HTMLDetailsElement>('[data-summary-answer] details');
    if (details) details.open = true;
    act(() => {
      phase(container, 'screening').click();
      phase(container, 'deep_dive').click();
      phase(container, 'citation').click();
      button(container, '읽기 안내').click();
    });
    act(() => button(container, '요약').click());
    await flushFrames();
    expect(phase(container, 'screening').getAttribute('aria-expanded')).toBe('false');
    expect(phase(container, 'deep_dive').getAttribute('aria-expanded')).toBe('false');
    expect(phase(container, 'citation').getAttribute('aria-expanded')).toBe('true');
    act(() => phase(container, 'deep_dive').click());
    expect(container.querySelector<HTMLDetailsElement>('[data-summary-answer] details')?.open).toBe(true);
    expect(chatWithAgent).not.toHaveBeenCalled();
  });

  it('opens a collapsed summary and focuses the matching answer on every explicit request', async () => {
    const container = await render();
    act(() => {
      phase(container, 'deep_dive').click();
      button(container, '읽기 안내').click();
    });
    const unrelated = document.createElement('h4');
    unrelated.dataset.summaryAnswer = '0';
    document.body.prepend(unrelated);
    act(() => button(container, '요약의 답변 보기').click());
    await flushFrames();
    expect(phase(container, 'deep_dive').getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(container.querySelector('[data-summary-answer="0"] h4'));
    expect(scrollTo).toHaveBeenLastCalledWith({ behavior: 'auto', top: 0 });
    expect(scrollIntoView).not.toHaveBeenCalled();
    const count = scrollTo.mock.calls.length;
    act(() => button(container, '읽기 안내').click());
    act(() => button(container, '요약의 답변 보기').click());
    await flushFrames();
    expect(scrollTo).toHaveBeenCalledTimes(count + 1);
    expect(chatWithAgent).not.toHaveBeenCalled();
  });

  it('restores summary scroll but lets an explicit answer request take priority', async () => {
    const container = await render();
    const scroller = container.querySelector<HTMLElement>('[data-analysis-scroll]');
    if (!scroller) throw new Error('Scroll container not found');
    scroller.scrollTop = 420;
    act(() => scroller.dispatchEvent(new Event('scroll')));
    act(() => button(container, '그림').click());
    scroller.scrollTop = 25;
    act(() => button(container, '요약').click());
    await flushFrames();
    expect(scroller.scrollTop).toBe(420);
    act(() => button(container, '읽기 안내').click());
    const heading = container.querySelector<HTMLElement>('[data-summary-answer="0"] h4');
    if (!heading) throw new Error('Answer heading not found');
    vi.spyOn(heading, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 340, 300, 24));
    act(() => button(container, '요약의 답변 보기').click());
    await flushFrames();
    expect(scroller.scrollTop).toBe(760);
  });

  it('preserves the reading position and existing text nodes when a citation opens a gallery', async () => {
    const container = await render();
    const onCitationClick = vi.fn();
    await act(async () => root?.render(panel(data, '1', null, onCitationClick)));
    const scroller = container.querySelector<HTMLElement>('[data-analysis-scroll]');
    const paragraph = container.querySelector('[data-summary-anchor="main"] p');
    const question = container.querySelector('[data-summary-answer] p');
    if (!scroller || !paragraph) throw new Error('Summary text not found');
    scroller.scrollTop = 1792;
    act(() => scroller.dispatchEvent(new Event('scroll')));
    const removeChild = Node.prototype.removeChild;
    const removal = vi.spyOn(Node.prototype, 'removeChild').mockImplementation(function <T extends Node>(this: Node, child: T): T {
      const result = removeChild.call(this, child) as T;
      if (paragraph.isSameNode(child)) {
        // jsdom has no layout. Model Chrome's observed scroll anchoring after text replacement.
        scroller.scrollTop = 344;
        scroller.dispatchEvent(new Event('scroll'));
      }
      return result;
    });
    try {
      await act(async () => root?.render(panel(data, '1', { tab: 'figures', anchor: 'figure-1', token: 1 }, onCitationClick)));
      act(() => button(container, '요약').click());
      await flushFrames();
      expect(scroller.scrollTop).toBe(1792);
      expect(container.querySelector('[data-summary-anchor="main"] p')).toBe(paragraph);
      expect(container.querySelector('[data-summary-answer] p')).toBe(question);
    } finally {
      removal.mockRestore();
    }
  });

  it('keeps selected answer text through an unrelated parent render', async () => {
    const container = await render();
    const onCitationClick = vi.fn();
    await act(async () => root?.render(panel(data, '1', null, onCitationClick)));
    const question = container.querySelector('[data-summary-answer] p');
    if (!question) throw new Error('Answer question not found');
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(question);
    selection?.removeAllRanges();
    selection?.addRange(range);
    await act(async () => root?.render(panel(data, '1', null, onCitationClick)));
    expect(selection?.toString()).toBe(answer.question);
  });

  it('focuses a cited gallery card only inside its reading panel without motion', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    try {
      const container = await render();
      const scroller = container.querySelector<HTMLElement>('[data-analysis-scroll]');
      if (!scroller) throw new Error('Reading panel not found');
      const outside = document.createElement('div');
      outside.dataset.citationAnchor = 'figure-1';
      document.body.prepend(outside);
      await act(async () => root?.render(panel(data, '1', { tab: 'figures', anchor: 'figure-1', token: 1 })));
      const card = container.querySelector<HTMLElement>('[data-citation-anchor="figure-1"]');
      if (!card) throw new Error('Figure card not found');
      vi.spyOn(scroller, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 240, 560, 660));
      vi.spyOn(card, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 640, 520, 400));
      act(() => vi.advanceTimersByTime(80));
      expect(scrollTo).toHaveBeenLastCalledWith({ behavior: 'auto', top: 400 });
      expect(document.activeElement).toBe(card);
      expect(scrollIntoView).not.toHaveBeenCalled();
      expect(container.scrollTop).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('resets disclosure and scroll state for another paper', async () => {
    const container = await render();
    const scroller = container.querySelector<HTMLElement>('[data-analysis-scroll]');
    if (scroller) scroller.scrollTop = 320;
    act(() => {
      phase(container, 'screening').click();
      phase(container, 'deep_dive').click();
      phase(container, 'citation').click();
      button(container, '읽기 안내').click();
    });
    await act(async () => root?.render(panel(data, '2')));
    await flushFrames();
    expect(phase(container, 'screening').getAttribute('aria-expanded')).toBe('true');
    expect(phase(container, 'deep_dive').getAttribute('aria-expanded')).toBe('true');
    expect(phase(container, 'citation').getAttribute('aria-expanded')).toBe('false');
    expect(scroller?.scrollTop).toBe(0);
    expect(chatWithAgent).not.toHaveBeenCalled();
  });

  it.each([{ detailed_analysis: '구형 장문' }, { ...data, section_answers: [answer, answer] }])(
    'uses whole-summary links for legacy and ambiguous titles without generation', async (payload) => {
      const container = await render(payload);
      act(() => button(container, '읽기 안내').click());
      expect(container.textContent).not.toContain('요약의 답변 보기');
      expect([...container.querySelectorAll('button')].filter((item) => item.textContent === '요약 전체 보기')).toHaveLength(2);
      expect(chatWithAgent).not.toHaveBeenCalled();
    },
  );

  it('marks malformed stored extensions as a phase error rather than a successful empty result', async () => {
    const container = await render({ problem_definition: '기존 본문', section_answers: [] });
    expect(phase(container, 'deep_dive').textContent).toContain('형식이 올바르지 않아요');
    expect(phase(container, 'deep_dive').textContent).not.toContain('완료');
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    expect(container.textContent).not.toContain('분석 완료');
  });

  it('uses immediate heading jumps for keyboard and reduced motion in the existing phase outline', async () => {
    const container = await render();
    vi.stubGlobal('matchMedia', () => ({ matches: false }));
    act(() => phase(container, 'citation').click());
    const outline = container.querySelector<HTMLButtonElement>('[data-phase="citation"] nav button');
    act(() => outline?.click());
    expect(scrollTo).toHaveBeenLastCalledWith({ behavior: 'auto', top: 0 });
    expect(document.activeElement?.textContent).toBe('First source');
    act(() => outline?.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })));
    expect(scrollTo).toHaveBeenLastCalledWith({ behavior: 'smooth', top: 0 });
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    act(() => outline?.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })));
    expect(scrollTo).toHaveBeenLastCalledWith({ behavior: 'auto', top: 0 });
    expect(outline?.classList.contains('min-h-8')).toBe(true);
  });

  it('moves only the reading panel and preserves overflow-hidden ancestors', async () => {
    const container = await render();
    const scroller = container.querySelector<HTMLElement>('[data-analysis-scroll]');
    const heading = container.querySelector<HTMLElement>('[data-summary-answer="0"] h4');
    if (!scroller || !heading) throw new Error('Reading target not found');
    vi.spyOn(scroller, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 240, 560, 660));
    vi.spyOn(heading, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 800, 520, 24));
    heading.style.scrollMarginTop = '20px';
    scrollIntoView.mockImplementation(() => { container.scrollTop = 240; });
    act(() => button(container, '읽기 안내').click());
    act(() => button(container, '요약의 답변 보기').click());
    await flushFrames();
    expect(container.scrollTop).toBe(0);
    expect(scroller.scrollTop).toBe(540);
    expect(document.activeElement).toBe(heading);
    scrollIntoView.mockReset();
  });
});
