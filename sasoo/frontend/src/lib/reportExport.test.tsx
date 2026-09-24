// @vitest-environment jsdom
import { expect, it } from 'vitest';
import { buildReportHtml } from './reportExport';

it.each([
  'https://review-probe.invalid/pixel?paper=SECURITY_SENTINEL',
  '//review-probe.invalid/pixel?paper=SECURITY_SENTINEL',
  'http://127.0.0.1:19328/pixel?paper=SECURITY_SENTINEL',
])('restricts automatic resources before an exported image can load: %s', (imageUrl) => {
  // Given
  const html = buildReportHtml({
    title: '비공개 논문 보고서',
    markdown: `![remote](${imageUrl})\n\n[원문 확인](https://example.org/paper)`,
  });

  // When
  const document = new DOMParser().parseFromString(html, 'text/html');

  // Then
  const policy = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
  expect(policy?.getAttribute('content')).toBe(
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'",
  );
  const resource = document.querySelector('link[rel="preload"][as="image"], img');
  expect(resource).not.toBeNull();
  expect(resource && policy?.compareDocumentPosition(resource)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  expect(document.querySelector('a')?.getAttribute('href')).toBe('https://example.org/paper');
});

it('preserves answers, sources, conditions, code and math in a standalone report', () => {
  const html = buildReportHtml({
    title: '검증용 보고서',
    markdown: '### 섹션별 핵심 답변\n\n질문과 **짧은 답**\n\n근거: Fig. 2\n\n### 옮겨 쓸 때 확인할 조건\n\n제공 자료에서 확인 못함\n\n확인 제안: 조건 확인\n\n```python\nx = 1\n  print(x)\n```\n\n$x^2$\n',
  });
  expect(html).toContain('<html lang="ko">');
  expect(html).toContain('<strong>짧은 답</strong>');
  expect(html).toContain('제공 자료에서 확인 못함');
  expect(html).toContain('근거: Fig. 2');
  expect(html).toContain('x = 1\n  print(x)\n');
  expect(html).toContain('<math');
});

it('escapes a report title and excludes executable raw markdown HTML', () => {
  const html = buildReportHtml({ title: '<script>bad()</script>', markdown: '<script>bad()</script>\n\n[safe](javascript:bad)' });
  expect(html).not.toContain('<script>');
  expect(html).not.toContain('href="javascript:');
  expect(html).toContain('&lt;script&gt;');
});
