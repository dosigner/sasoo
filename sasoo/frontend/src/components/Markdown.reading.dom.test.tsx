// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Markdown, ReadingInlineText } from './Markdown';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root | null = null;

function render(content: ReactNode) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const mountedRoot = createRoot(container);
  root = mountedRoot;
  act(() => mountedRoot.render(content));
  return container;
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('reading Markdown', () => {
  it('groups Korean auxiliary phrases with their trailing punctuation only in reading mode', () => {
    // Given
    const source = '요구할 수 있는지를 묻습니다. 치우칠 수 있고, 알 수 없어요. “쓸 수 있지만!”';

    // When
    const container = render(<><Markdown codeTools>{source}</Markdown><Markdown>{source}</Markdown></>);

    // Then
    expect([...container.querySelectorAll('.reading-auxiliary')].map((node) => node.textContent))
      .toEqual(['요구할 수 있는지를', '치우칠 수 있고,', '알 수 없어요.', '쓸 수 있지만!”']);
    expect([...container.querySelectorAll('p')].map((node) => node.textContent)).toEqual([source, source]);
    expect(container.lastElementChild?.querySelector('.reading-auxiliary')).toBeNull();
  });

  it('preserves mixed emphasis, parentheses, links, code and math around auxiliary groups', () => {
    // Given
    const source = '**요구할 수 있는지를** 묻고 *알 수 없지만,* (조건을 볼 수 있다) `쓸 수 있다` [볼 수 있다](https://example.org) $f(x)$';

    // When
    const container = render(<Markdown codeTools>{source}</Markdown>);

    // Then
    expect(container.textContent).toContain('요구할 수 있는지를 묻고 알 수 없지만, (조건을 볼 수 있다) 쓸 수 있다 볼 수 있다');
    expect(container.querySelector('strong .reading-auxiliary')?.textContent).toBe('요구할 수 있는지를');
    expect(container.querySelector('em .reading-auxiliary')?.textContent).toBe('알 수 없지만,');
    expect(container.querySelector('.reading-parenthetical')?.textContent).toBe('(조건을 볼 수 있다)');
    expect(container.querySelector('code .reading-auxiliary, a .reading-auxiliary, .katex .reading-auxiliary')).toBeNull();
    expect(container.querySelectorAll('.katex').length).toBe(1);
  });

  it('retains all text in an auxiliary group longer than a reading pane', () => {
    // Given
    const source = `${'긴'.repeat(120)}구절을 수 없어요.`;

    // When
    const container = render(<Markdown codeTools>{source}</Markdown>);

    // Then
    expect(container.querySelector('.reading-auxiliary')?.textContent).toBe(source);
    expect(container.textContent).toBe(source);
  });

  it('groups plain caption names while preserving escaped text and literal Markdown', () => {
    // Given
    const caption = '<script>alert(1)</script> **Table 1** (max performance)';

    // When
    const container = render(<p className="text-sm"><ReadingInlineText>{caption}</ReadingInlineText></p>);

    // Then
    expect(container.textContent).toBe(caption);
    expect(container.querySelector('script, strong, pre, button')).toBeNull();
    expect(container.querySelector('.reading-parenthetical')?.textContent).toBe('(1)');
    expect([...container.querySelectorAll('.reading-parenthetical')].map((node) => node.textContent))
      .toContain('(max performance)');
    expect(container.firstElementChild?.className).toBe('text-sm');
  });

  it('groups source titles and names only in reading mode without changing their text', () => {
    // Given
    const source = '행동 복제(behavior cloning)를 설명해요. (9 Limitations and Future Work) (5.2 Evaluation Methodology, Table 6)';

    // When
    const container = render(<><Markdown codeTools>{source}</Markdown><Markdown>{source}</Markdown></>);

    // Then
    expect([...container.querySelectorAll('.reading-parenthetical')].map((node) => node.textContent))
      .toEqual(['(behavior cloning)', '(9 Limitations and Future Work)', '(5.2 Evaluation Methodology', 'Table 6)']);
    expect([...container.querySelectorAll('p')].map((node) => node.textContent)).toEqual([source, source]);
    expect(container.lastElementChild?.querySelector('.reading-parenthetical')).toBeNull();
  });

  it('keeps long parentheticals intact and leaves code, links and math untouched', () => {
    // Given
    const name = `(${Array.from({ length: 40 }, () => 'long source title').join(' ')})`;
    const source = `${name}\n\n\`(code name)\` [link (source name)](https://example.org) $f(x)$`;

    // When
    const container = render(<Markdown codeTools>{source}</Markdown>);

    // Then
    expect(container.querySelector('.reading-parenthetical')?.textContent).toBe(name);
    expect(container.querySelectorAll('.reading-parenthetical').length).toBe(1);
    expect(container.querySelector('code .reading-parenthetical, a .reading-parenthetical, .katex .reading-parenthetical')).toBeNull();
    expect(container.querySelector('code')?.textContent).toBe('(code name)');
    expect(container.querySelector('a')?.textContent).toBe('link (source name)');
    expect(container.querySelectorAll('.katex').length).toBe(1);
  });

  it('keeps allowed source navigation inside a reading parenthetical', () => {
    // Given
    const onClick = vi.fn();

    // When
    const container = render(<Markdown codeTools citations={{ onClick }}>{'근거 (Fig. 2)'}</Markdown>);

    // Then
    const chip = container.querySelector<HTMLButtonElement>('.reading-parenthetical .citation-chip');
    expect(chip?.textContent).toBe('Fig. 2');
    act(() => chip?.click());
    expect(onClick).toHaveBeenCalledWith({ type: 'figure', n: 2 });
    expect(container.textContent).toBe('근거 (Fig. 2)');
  });

  it('adds highlighting and copy tools only when codeTools is enabled', () => {
    // Given
    const source = '```python\nx = 1\nprint(x)\n```';

    // When
    const container = render(<Markdown codeTools>{source}</Markdown>);

    // Then
    expect(container.querySelector('button')?.textContent).toBe('코드 복사');
    expect(container.querySelector('.reading-code-language')?.textContent).toBe('python');
    expect(container.querySelector('code .hljs-number')?.textContent).toBe('1');
    expect(container.querySelector('pre code')?.textContent).toBe('x = 1\nprint(x)\n');
  });

  it('preserves the default Markdown shape and plain code for other consumers', () => {
    // Given
    const source = '```python\nx = 1\n```';

    // When
    const container = render(<Markdown>{source}</Markdown>);

    // Then
    expect(container.firstElementChild?.tagName).toBe('PRE');
    expect(container.querySelector('button, .hljs-number, .reading-code-block')).toBeNull();
    expect(container.querySelector('pre code')?.textContent).toBe('x = 1\n');
  });

  it('keeps emphasis, math, heading anchors and citation exclusions in reading mode', () => {
    // Given
    const onCitation = vi.fn();
    const source = [
      '## 방법 $x^2$',
      '',
      '**중요한 조건**에서 *E. coli*를 관찰해요. Fig. 3을 참고해요.',
      '',
      '`Fig. 3`와 [Fig. 3](https://example.org/figure)는 원래 표기를 유지해요.',
      '',
      '$$x^2 + y^2 = z^2$$',
      '',
      '```python',
      'print("Fig. 3")',
      '```',
    ].join('\n');

    // When
    const container = render(
      <Markdown codeTools headingAnchors citations={{ onClick: onCitation }}>{source}</Markdown>,
    );

    // Then
    expect(container.querySelector('em')?.textContent).toBe('E. coli');
    expect(container.querySelector('strong')?.textContent).toBe('중요한 조건');
    expect(container.querySelector('h2')?.id).toBe('방법-x-2');
    expect(container.querySelectorAll('.katex').length).toBe(2);
    expect(container.querySelectorAll('.citation-chip').length).toBe(1);
    expect(container.querySelector('code .citation-chip, a .citation-chip')).toBeNull();
    expect(container.querySelectorAll('.reading-code-block').length).toBe(1);
  });

  it('renders unsupported and unspecified languages as plain text without guessing', () => {
    // Given
    const source = '```sasoo-unknown-language\nFig. 3 <script>x = 1</script>\n```\n\n```\nx = 1\n```';

    // When
    const container = render(<Markdown codeTools>{source}</Markdown>);

    // Then
    const blocks = container.querySelectorAll('pre code');
    expect(blocks[0]?.textContent).toBe('Fig. 3 <script>x = 1</script>\n');
    expect(blocks[0]?.children.length).toBe(0);
    expect(blocks[1]?.textContent).toBe('x = 1\n');
    expect(blocks[1]?.className).toBe('');
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelectorAll('.reading-code-language')[1]?.textContent).toBe('코드');
  });

  it('keeps custom Markdown components when reading tools are enabled', () => {
    // Given
    const source = '앞문장 `inline` 뒷문장';

    // When
    const container = render(
      <Markdown codeTools components={{ p: ({ children }) => <p data-custom="true">{children}</p> }}>
        {source}
      </Markdown>,
    );

    // Then
    expect(container.querySelector('p')?.dataset.custom).toBe('true');
    expect(container.querySelector('code')?.textContent).toBe('inline');
    expect(container.querySelector('button')).toBeNull();
  });
});
