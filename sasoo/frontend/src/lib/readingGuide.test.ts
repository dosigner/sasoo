import { describe, expect, it } from 'vitest';

import { buildReadingGuidePrompt, glossarySearchTerm, parseReadingGuide } from './readingGuide';

const FULL = `## 표기 사전
- **λ** (p.3): 자유 공간 파장이에요.
- **NA** (p. 4): 대물렌즈의 개구수예요.
- σ (페이지 7): 표면 거칠기의 RMS 값이에요.
- **k**: 파수예요.

## 선행 지식
- **푸리에 광학**: 렌즈가 초점면에서 푸리에 변환을 만든다는 관점이에요. 회절 적분을 한 번의 곱으로 바꿔요. 이 논문에서: 전파 연산자를 행렬 곱으로 줄이는 근거예요.
- **적응 광학**: 파면 오차를 실시간으로 보정하는 기법이에요.

## 섹션별 직관
### 1. Introduction (p.1)
왜 이 문제가 아직 안 풀렸는지 배경을 깔아요.

두 번째 단락이에요.

### 2. Method (p.4)
제안 방법이 무엇을 하려는지 설명해요.

### 3. Results
수치를 나열하지 않고 경향만 봐요.
`;

describe('parseReadingGuide', () => {
  it('세 섹션을 모두 구조로 되돌린다', () => {
    const guide = parseReadingGuide(FULL);

    expect(guide.parsed).toBe(true);
    expect(guide.glossary).toHaveLength(4);
    expect(guide.glossary[0]).toEqual({
      symbol: 'λ',
      meaning: '자유 공간 파장이에요.',
      page: 3,
    });
    expect(guide.prerequisites).toHaveLength(2);
    expect(guide.prerequisites[0].name).toBe('푸리에 광학');
    expect(guide.prerequisites[0].why).toBe('전파 연산자를 행렬 곱으로 줄이는 근거예요.');
    expect(guide.prerequisites[0].primer).not.toContain('이 논문에서');
    expect(guide.sections.map((s) => s.title)).toEqual([
      '1. Introduction',
      '2. Method',
      '3. Results',
    ]);
    expect(guide.sections[0].body).toBe(
      '왜 이 문제가 아직 안 풀렸는지 배경을 깔아요.\n\n두 번째 단락이에요.',
    );
  });

  it('페이지 표기가 없으면 page는 null이다', () => {
    const guide = parseReadingGuide(FULL);

    expect(guide.glossary[3]).toEqual({ symbol: 'k', meaning: '파수예요.', page: null });
    expect(guide.prerequisites[1].why).toBeNull();
    expect(guide.sections[2].page).toBeNull();
  });

  it('p. 4 와 페이지 7 같은 표기 변형을 받아들인다', () => {
    const guide = parseReadingGuide(FULL);

    expect(guide.glossary[1].page).toBe(4);
    expect(guide.glossary[2]).toEqual({
      symbol: 'σ',
      meaning: '표면 거칠기의 RMS 값이에요.',
      page: 7,
    });
  });

  it('헤딩이 없으면 parsed=false로 raw를 남긴다', () => {
    const raw = '- **λ**: 파장이에요.\n그냥 문단이에요.';
    const guide = parseReadingGuide(raw);

    expect(guide.parsed).toBe(false);
    expect(guide.raw).toBe(raw);
    expect(guide.glossary).toHaveLength(0);
    expect(guide.prerequisites).toHaveLength(0);
    expect(guide.sections).toHaveLength(0);
  });

  it('빈 입력도 parsed=false로 안전하게 돌려준다', () => {
    const guide = parseReadingGuide('');

    expect(guide.parsed).toBe(false);
    expect(guide.raw).toBe('');
    expect(guide.sections).toHaveLength(0);
  });

  it('헤딩만 있고 항목이 하나도 없으면 parsed=false다', () => {
    const guide = parseReadingGuide('## 표기 사전\n\n## 선행 지식\n\n## 섹션별 직관\n');

    expect(guide.parsed).toBe(false);
  });
});

describe('buildReadingGuidePrompt', () => {
  it('세 개의 고정 헤딩을 형식으로 지정한다', () => {
    const prompt = buildReadingGuidePrompt(null);

    expect(prompt).toContain('## 표기 사전');
    expect(prompt).toContain('## 선행 지식');
    expect(prompt).toContain('## 섹션별 직관');
    expect(prompt).toContain('유도는 쓰지 마세요');
  });

  it('설명 수준이 있으면 그 라벨을 눈높이로 넣는다', () => {
    expect(buildReadingGuidePrompt('masters')).toContain('석사생');
    expect(buildReadingGuidePrompt('elementary')).toContain('초등학생');
    expect(buildReadingGuidePrompt('unknown-level')).not.toContain('읽는 사람은 이에요');
  });
});

describe('glossarySearchTerm', () => {
  it('수식 델리미터만 벗기고 그대로 검색한다', () => {
    expect(glossarySearchTerm('CNF')).toBe('CNF');
    expect(glossarySearchTerm('\\(t\\)')).toBe('t');
    expect(glossarySearchTerm('$\\lambda$')).toBeNull();
    expect(glossarySearchTerm('push-forward')).toBe('push-forward');
  });

  it('TeX 명령이나 첨자가 남으면 검색어를 내지 않는다', () => {
    expect(glossarySearchTerm('\\(p_t\\)')).toBeNull();
    expect(glossarySearchTerm('\\(x \\in \\mathbb{R}^d\\)')).toBeNull();
    expect(glossarySearchTerm('\\(v_t(x)\\)')).toBeNull();
    expect(glossarySearchTerm('')).toBeNull();
  });
});
