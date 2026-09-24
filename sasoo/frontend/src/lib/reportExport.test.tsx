import { expect, it } from 'vitest';
import { buildReportHtml } from './reportExport';

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
