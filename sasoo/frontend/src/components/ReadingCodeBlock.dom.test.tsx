// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { ReadingCodeBlock } from './ReadingCodeBlock';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
const writeText = vi.fn<(text: string) => Promise<void>>();
let root: Root | null = null;

function renderCode(content: ReactNode = 'x = 1\nprint(x)\n') {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const mountedRoot = createRoot(container);
  root = mountedRoot;
  act(() => mountedRoot.render(
    <ReadingCodeBlock><code className="language-python">{content}</code></ReadingCodeBlock>,
  ));
  return container;
}

beforeEach(() => {
  vi.useFakeTimers();
  writeText.mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
  if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor);
  else Reflect.deleteProperty(navigator, 'clipboard');
  vi.useRealTimers();
  vi.resetAllMocks();
});

describe('ReadingCodeBlock', () => {
  it('copies the rendered code text and announces success when the clipboard accepts it', async () => {
    // Given
    const container = renderCode(<>x = <span className="hljs-number">1</span>{'\nprint(x)\n'}</>);

    // When
    await act(async () => container.querySelector('button')?.click());

    // Then
    expect(writeText).toHaveBeenCalledWith('x = 1\nprint(x)\n');
    expect(container.querySelector('button')?.textContent).toBe('복사했어요');
    expect(container.querySelector('[role="status"]')?.textContent).toBe('복사했어요');
    expect(container.querySelector('button')?.getAttribute('aria-label')).toBe('코드 복사');
  });

  it.each([
    { delay: 1499, label: '복사했어요' },
    { delay: 1500, label: '코드 복사' },
  ])('shows $label after $delay ms when copying succeeds', async ({ delay, label }) => {
    // Given
    const container = renderCode();
    await act(async () => container.querySelector('button')?.click());

    // When
    act(() => vi.advanceTimersByTime(delay));

    // Then
    expect(container.querySelector('button')?.textContent).toBe(label);
  });

  it('announces failure without success when the clipboard rejects the write', async () => {
    // Given
    writeText.mockRejectedValue(new DOMException('Denied', 'NotAllowedError'));
    const container = renderCode();

    // When
    await act(async () => container.querySelector('button')?.click());

    // Then
    expect(container.querySelector('[role="status"]')?.textContent).toBe('복사하지 못했어요');
    expect(container.textContent).not.toContain('복사했어요');
    expect(vi.getTimerCount()).toBe(0);
    expect(container.querySelector('button')?.disabled).toBe(false);
  });

  it('announces failure when the clipboard API is unavailable', async () => {
    // Given
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
    const container = renderCode();

    // When
    await act(async () => container.querySelector('button')?.click());

    // Then
    expect(container.querySelector('[role="status"]')?.textContent).toBe('복사하지 못했어요');
    expect(container.textContent).not.toContain('복사했어요');
  });

  it.each(['', `  ${'very_long_identifier_'.repeat(100)}\n\tprint("Fig. 3")\n`])(
    'preserves empty code and long lines without rewriting whitespace',
    async (source) => {
      // Given
      const container = renderCode(source);

      // When
      await act(async () => container.querySelector('button')?.click());

      // Then
      expect(writeText).toHaveBeenCalledWith(source);
      expect(container.querySelector('pre')?.tabIndex).toBe(0);
    },
  );

  it('clears success feedback timers when the component unmounts', async () => {
    // Given
    const container = renderCode();
    await act(async () => container.querySelector('button')?.click());
    expect(vi.getTimerCount()).toBe(1);

    // When
    act(() => root?.unmount());
    root = null;

    // Then
    expect(vi.getTimerCount()).toBe(0);
  });

  it('avoids delayed state work when a pending clipboard write completes after unmount', async () => {
    // Given
    const pending = Promise.withResolvers<void>();
    writeText.mockReturnValue(pending.promise);
    const container = renderCode();
    act(() => container.querySelector('button')?.click());
    expect(container.querySelector('button')?.disabled).toBe(true);
    act(() => root?.unmount());
    root = null;

    // When
    await act(async () => pending.resolve());

    // Then
    expect(vi.getTimerCount()).toBe(0);
  });
});
