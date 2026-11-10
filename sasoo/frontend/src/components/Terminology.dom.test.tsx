// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import ReadingGuideProvider from './ReadingGuideProvider';
import TerminologyTab from './TerminologyTab';
import { Markdown } from './Markdown';
import { TooltipProvider } from './ui/Tooltip';

const { getGuide, setGuide, chatWithAgent } = vi.hoisted(() => ({ getGuide: vi.fn(), setGuide: vi.fn(), chatWithAgent: vi.fn() }));
vi.mock('@/lib/guideCache', () => ({ getGuide, setGuide }));
vi.mock('@/lib/api', () => ({ chatWithAgent }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const content = `## 용어 사전
- **overfitting**: 과적합 | 학습 데이터에 지나치게 맞춰진 상태. | 분야 기본
- **underfitting**: 과소적합 | 학습 데이터의 구조도 충분히 학습하지 못한 상태. | 분야 기본
- **regularization** (p.4): 정규화 | 학습에 제약을 두는 방법. | 논문
- **validation**: 검증 | 별도 데이터로 성능을 확인하는 과정. | 분야 기본
## 섹션별 직관
### Methods
기존 안내 본문.
`;
const record = (markdown = content) => ({ markdown, createdAt: 1, level: 'masters', costUsd: 0.02 });
let root: Root | null = null;
let container: HTMLDivElement;

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  getGuide.mockResolvedValue(record());
  setGuide.mockResolvedValue(undefined);
});
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});

async function render(children: ReactNode, paperId = '1') {
  await act(async () => root?.render(<TooltipProvider><ReadingGuideProvider paperId={paperId} level="masters">
    {children}
  </ReadingGuideProvider></TooltipProvider>));
}
async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => (element as HTMLElement).click());
}
async function search(value: string) {
  const input = container.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
function button(label: string) {
  return [...document.querySelectorAll('button')].find(node => node.textContent === label);
}

describe('terminology in the workbench', () => {
  it('adds accessible English triggers without changing links, code, math or text', async () => {
    await render(<Markdown headingAnchors>{`## overfitting
**overfitting**을 줄인다. [**overfitting**](https://example.org)과 \`overfitting\`, $\\text{overfitting}$.
\n\n\`\`\`txt\noverfitting\n\`\`\``}</Markdown>);
    expect(container.querySelector('h2')?.id).toBe('overfitting');
    expect(container.querySelectorAll('[data-terminology]')).toHaveLength(2);
    expect(container.querySelector('a [data-terminology], code [data-terminology], .katex [data-terminology]')).toBeNull();
    const term = container.querySelector<HTMLElement>('[data-terminology]')!;
    expect(term.tabIndex).toBe(0);
    await act(async () => { term.focus(); });
    expect(document.querySelector('[role="tooltip"]')?.textContent).toContain('과적합');
    await act(async () => term.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(document.querySelector('[role="tooltip"]')).toBeNull();
    expect(chatWithAgent).not.toHaveBeenCalled();
  });

  it('searches in both languages, preserves comparisons across searches and limits selection to three', async () => {
    const onSearch = vi.fn();
    await render(<TerminologyTab paperId="1" onSearchInPdf={onSearch} />);
    await click(container.querySelector('[aria-label="overfitting 비교 선택"]'));
    await search('정규화');
    expect(container.querySelector('[aria-label="용어 목록"]')?.textContent).toContain('regularization');
    expect(container.querySelector('[aria-label="용어 목록"]')?.textContent).not.toContain('underfitting');
    await click(container.querySelector('[aria-label="regularization 비교 선택"]'));
    expect(container.querySelector('table')?.textContent).toContain('overfitting');
    expect(container.querySelector('table')?.textContent).toContain('정규화');
    await click(button('p.4에서 찾기'));
    expect(onSearch).toHaveBeenCalledWith('regularization', 4);
    await search('');
    await click(container.querySelector('[aria-label="underfitting 비교 선택"]'));
    expect(container.querySelector<HTMLInputElement>('[aria-label="validation 비교 선택"]')?.disabled).toBe(true);
    await click(button('선택 해제'));
    expect(container.querySelector('table')).toBeNull();
    await search('missing term');
    expect(container.textContent).toContain('일치하는 용어가 없어요');
    expect(getGuide).toHaveBeenCalledTimes(1);
    expect(chatWithAgent).not.toHaveBeenCalled();
  });

  it('retries a failed cache read without generating or charging a request', async () => {
    getGuide.mockRejectedValueOnce(new Error('cache read failed'));
    await render(<TerminologyTab paperId="1" />);
    expect(container.textContent).toContain('사전을 불러오지 못했어요');
    expect(container.textContent).not.toContain('영어 용어를 읽다가');
    await click(button('다시 불러오기'));
    expect(container.textContent).toContain('overfitting');
    expect(chatWithAgent).not.toHaveBeenCalled();
  });

  it('keeps the saved dictionary when regeneration returns an invalid format', async () => {
    chatWithAgent.mockImplementation(async (_id, _prompt, _history, onToken, onDone) => {
      onToken('## 섹션별 직관\n### Methods\n사전이 빠진 응답');
      onDone({ cost_usd: 0.01 });
    });
    await render(<TerminologyTab paperId="1" />);
    await click(button('다시 만들기'));
    expect(chatWithAgent).not.toHaveBeenCalled();
    await click(button('만들기'));
    expect(container.textContent).toContain('사전을 만들지 못했어요');
    expect(container.textContent).toContain('overfitting');
    expect(setGuide).not.toHaveBeenCalled();
  });

  it('stores one completed guide and immediately updates both the tab and inline definitions', async () => {
    getGuide.mockResolvedValue(null);
    chatWithAgent.mockImplementation(async (_id, _prompt, _history, onToken, onDone) => {
      onToken(content);
      onDone({ cost_usd: 0.03 });
    });
    await render(<><Markdown>overfitting을 확인한다.</Markdown><TerminologyTab paperId="1" /></>);
    expect(container.querySelector('[data-terminology]')).toBeNull();
    await click(button('사전 만들기'));
    await click(button('만들기'));
    expect(setGuide).toHaveBeenCalledWith('1', expect.objectContaining({ markdown: content, costUsd: 0.03 }));
    expect(container.querySelector('[data-terminology]')?.textContent).toBe('overfitting');
    expect(container.querySelector('[aria-label="용어 목록"]')?.textContent).toContain('과적합');
    expect(chatWithAgent).toHaveBeenCalledTimes(1);
  });

  it('drops removed comparison terms when regeneration replaces the dictionary', async () => {
    const replacement = `## 용어 사전
- **training set**: 학습 데이터 | 학습에 쓰는 데이터. | 분야 기본
- **test set**: 시험 데이터 | 최종 평가에 쓰는 데이터. | 분야 기본`;
    chatWithAgent.mockImplementation(async (_id, _prompt, _history, onToken, onDone) => {
      onToken(replacement);
      onDone({ cost_usd: 0.02 });
    });
    await render(<TerminologyTab paperId="1" />);
    for (const term of ['overfitting', 'underfitting', 'regularization']) {
      await click(container.querySelector(`[aria-label="${term} 비교 선택"]`));
    }
    expect(container.querySelector('table')?.textContent).toContain('overfitting');
    await click(button('다시 만들기'));
    await click(button('만들기'));
    expect(container.querySelector('table')).toBeNull();
    await click(container.querySelector('[aria-label="training set 비교 선택"]'));
    await click(container.querySelector('[aria-label="test set 비교 선택"]'));
    expect(container.querySelector('table')?.textContent).toContain('training set');
    expect(container.querySelector('table')?.textContent).toContain('test set');
    expect(container.querySelector('table')?.textContent).not.toContain('overfitting');
  });

  it('does not leak a cancelled late response into another paper or its cache', async () => {
    let finish: () => void = () => {};
    let lateToken: (text: string) => void = () => {};
    let lateDone: (meta: object) => void = () => {};
    chatWithAgent.mockImplementation((_id, _prompt, _history, onToken, onDone) => {
      lateToken = onToken;
      lateDone = onDone;
      return new Promise<void>(resolve => { finish = resolve; });
    });
    await render(<TerminologyTab paperId="1" />);
    await click(button('다시 만들기'));
    await click(button('만들기'));
    getGuide.mockResolvedValue(null);
    await render(<TerminologyTab paperId="2" />, '2');
    await act(async () => { lateToken(content); lateDone({ cost_usd: 0.03 }); finish(); });
    expect(container.querySelector('[aria-label="용어 목록"]')).toBeNull();
    expect(setGuide).not.toHaveBeenCalled();
  });
});
