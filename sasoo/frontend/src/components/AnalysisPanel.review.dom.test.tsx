// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { AnalysisResults, AnalysisStatus, ReviewMap } from '@/lib/api';
import AnalysisPanel from './AnalysisPanel';
import ReadingGuideProvider from './ReadingGuideProvider';

vi.mock('@/lib/api', () => ({ chatWithAgent: vi.fn() }));
vi.mock('@/lib/guideCache', () => ({ getGuide: vi.fn().mockResolvedValue(null), setGuide: vi.fn() }));
vi.mock('./FigureGallery', () => ({ default: () => null }));
vi.mock('./TableGallery', () => ({ default: () => null }));
vi.mock('./RecipeCard', () => ({ default: () => null }));
vi.mock('./ExperimentPlanTab', () => ({ default: () => null }));
vi.mock('./ReportExport', () => ({ default: () => null }));
vi.mock('./synthesis/SynthesisView', () => ({ SynthesisView: () => null }));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
});

const status: AnalysisStatus = {
  paper_id: 1, overall_status: 'completed', progress_pct: 100, current_phase: null,
  total_cost_usd: 0, total_tokens_in: 0, total_tokens_out: 0, phases: [],
};
const reviewSkip = { skipped: true, reason: 'review_paper', message: 'Review 논문이라 Deep Dive 대신 리뷰 지도를 만들었습니다.' };
const reviewMap: ReviewMap = {
  field_overview: '자유공간 광통신 전체를 다룬다.',
  parts: [
    { title: '2. Channel models', page: 3, subfield: '대기 채널', summary: '난류 모델 정리',
      development: '경험 모델에서 물리 모델로', takeaway: '난류 세기가 핵심 변수' },
    { title: '3. Adaptive optics', subfield: '파면 보정', summary: 'AO 정리', development: '센서 기반에서 센서리스로', takeaway: '대역폭 한계' },
  ],
  future_directions: [{ need: '실측 데이터 부족', research: '장거리 실험' }],
  reading_paths: [{ goal: '분야 입문', order: ['2. Channel models', '3. Adaptive optics'] }],
};

async function render(results: Partial<AnalysisResults>) {
  const full: AnalysisResults = {
    paper_id: 1, status, screening: { summary: '스크리닝 본문', paper_type: 'review' },
    citation: null, visual: null, recipe: null, deep_dive: null, ...results,
  };
  const container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root!.render(
    <ReadingGuideProvider paperId="1"><AnalysisPanel status={status} results={full} paperId="1" figures={null}
      tables={null} recipe={null} mermaid={null} visualizations={null} isRunning={false} /></ReadingGuideProvider>,
  ));
  return container;
}

const tabLabels = (container: HTMLElement) =>
  [...container.querySelectorAll('button')].map((node) => node.textContent ?? '');

describe('AnalysisPanel review map', () => {
  it('opens the review map tab with field, parts, future, and reading order for review papers', async () => {
    const container = await render({ deep_dive: reviewSkip, review_map: reviewMap });
    expect(tabLabels(container)).toContain('리뷰 지도');
    const text = container.textContent ?? '';
    for (const expected of ['대분야', '자유공간 광통신 전체를 다룬다.', '파트별 지도', '2. Channel models', '대기 채널',
      '발전 흐름', '경험 모델에서 물리 모델로', '읽는 법', '앞으로의 과제', '장거리 실험', '읽는 순서', '분야 입문', 'p.3']) {
      expect(text).toContain(expected);
    }
  });

  it('hides the tab for article papers and explains a failed review map', async () => {
    const article = await render({ deep_dive: { problem_definition: '문제', section_answers: [], transfer_checks: [] } });
    expect(tabLabels(article)).not.toContain('리뷰 지도');
    act(() => root?.unmount());
    document.body.innerHTML = '';

    const failed = await render({ deep_dive: reviewSkip, review_map: { error: '리뷰 지도를 만들지 못했어요' } as unknown as ReviewMap });
    expect(tabLabels(failed)).toContain('리뷰 지도');
    const tab = [...failed.querySelectorAll('button')].find((node) => node.textContent === '리뷰 지도')!;
    await act(async () => tab.click());
    expect(failed.textContent).toContain('리뷰 지도를 읽지 못했어요');
  });
});
