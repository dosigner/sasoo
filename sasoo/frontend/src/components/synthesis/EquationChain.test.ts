import { describe, expect, it } from 'vitest';
import { renderEquation } from './EquationChain';

describe('renderEquation', () => {
  it('유효한 LaTeX는 KaTeX HTML로 렌더한다', () => {
    const out = renderEquation('x_\\tau = (1 - \\tau) x_0 + \\tau x_1');
    expect('html' in out).toBe(true);
    if ('html' in out) expect(out.html).toContain('katex');
  });

  it('파싱 실패는 예외 대신 오류 값으로 돌려준다(원문을 그 자리에 두기 위해)', () => {
    const out = renderEquation('\\frac{a}{');
    expect('error' in out).toBe(true);
  });
});
