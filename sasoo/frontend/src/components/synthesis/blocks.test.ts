import { describe, expect, it } from 'vitest';
import { problemFields } from './blocks';

describe('problemFields', () => {
  it('문자열과 문자열 배열을 모두 본문으로 읽는다', () => {
    const f = problemFields({ as_is: '  기존 방식  ', to_be: ['목표 1', 2, '목표 2'], solution: null });
    expect(f).toEqual({ asIs: '기존 방식', toBe: '목표 1\n목표 2', solution: '' });
  });

  it('deep_dive가 없으면 전부 빈 문자열이라 구획이 숨는다', () => {
    expect(problemFields(null)).toEqual({ asIs: '', toBe: '', solution: '' });
  });
});
