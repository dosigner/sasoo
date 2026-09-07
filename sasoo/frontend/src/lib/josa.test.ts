import { describe, it, expect } from 'vitest';

import { withRoJosa } from './josa';

describe('withRoJosa', () => {
  it('모음으로 끝나는 숫자(이·사·오·구) 뒤에는 "로"를 붙인다', () => {
    expect(withRoJosa('그림 2')).toBe('그림 2로');
    expect(withRoJosa('표 4')).toBe('표 4로');
    expect(withRoJosa('표 5')).toBe('표 5로');
    expect(withRoJosa('Fig. 9')).toBe('Fig. 9로');
  });

  it('ㄹ 받침 숫자(일·칠·팔) 뒤에도 "로"를 붙인다', () => {
    expect(withRoJosa('Table 1')).toBe('Table 1로');
    expect(withRoJosa('Fig. 7')).toBe('Fig. 7로');
    expect(withRoJosa('표 8')).toBe('표 8로');
  });

  it('그 밖의 받침 숫자(영·삼·육) 뒤에는 "으로"를 붙인다', () => {
    expect(withRoJosa('표 0')).toBe('표 0으로');
    expect(withRoJosa('Fig. 3')).toBe('Fig. 3으로');
    expect(withRoJosa('표 6')).toBe('표 6으로');
  });

  it('두 자리 이상도 마지막 음절의 끝소리를 따른다', () => {
    expect(withRoJosa('Table 10')).toBe('Table 10으로'); // 십(ㅂ)
    expect(withRoJosa('표 20')).toBe('표 20으로'); // 이십(ㅂ)
    expect(withRoJosa('표 23')).toBe('표 23으로'); // 이십삼(ㅁ)
    expect(withRoJosa('표 24')).toBe('표 24로'); // 이십사(모음)
    expect(withRoJosa('p. 11')).toBe('p. 11로'); // 십일(ㄹ)
  });

  it('한글로 끝나면 받침 종류를 따른다(ㄹ 받침은 "로")', () => {
    expect(withRoJosa('12페이지')).toBe('12페이지로');
    expect(withRoJosa('결론')).toBe('결론으로');
    expect(withRoJosa('서울')).toBe('서울로');
  });
});
