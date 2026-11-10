import { describe, expect, it } from 'vitest';
import { parseReadingGuide } from './readingGuide';
import { dictionaryTerms, matchTerms } from './terminology';

const guide = () => parseReadingGuide(`## 용어 사전
- **Flow Matching (FM)** (p.4): 흐름 매칭 | 확률 경로를 따르는 벡터장을 학습하는 방법. | 논문
- **flow**: 흐름 | 상태가 연속적으로 변하는 과정. | 분야 기본
- **overfitting**: 과적합 | 학습 데이터에 지나치게 맞춰진 상태. | 분야 기본
## 섹션별 직관
### 2. Methods (p.4)
원래 읽기 안내 본문.
`);

describe('terminology dictionary', () => {
  it('keeps English terms, Korean names, provenance and page separately', () => {
    const parsed = guide();
    expect(parsed.terminology[0]).toEqual({ term: 'Flow Matching (FM)', korean: '흐름 매칭',
      definition: '확률 경로를 따르는 벡터장을 학습하는 방법.', scope: 'paper', page: 4 });
    expect(parsed.terminology[1].scope).toBe('field');
    expect(parsed.sections[0].body).toBe('원래 읽기 안내 본문.');
  });

  it('matches the longest phrase, preserves Korean particles and acronym case', () => {
    const text = 'Flow Matching은 flow와 FM을 쓴다. fm, overflow, overfitting도 구분한다.';
    expect(matchTerms(text, dictionaryTerms(guide())).map(m => text.slice(m.start, m.end)))
      .toEqual(['Flow Matching', 'flow', 'FM', 'overfitting']);
  });

  it('does not assign an ambiguous abbreviation to one meaning', () => {
    const parsed = parseReadingGuide(`## 용어 사전
- **Flow Matching (FM)**: 흐름 매칭 | 벡터장 학습. | 논문
- **Frequency Modulation (FM)**: 주파수 변조 | 주파수를 바꾸는 변조. | 논문`);
    const text = 'FM and Frequency Modulation';
    expect(matchTerms(text, dictionaryTerms(parsed)).map(m => text.slice(m.start, m.end)))
      .toEqual(['Frequency Modulation']);
  });

  it('reuses old English glossary entries without inventing Korean names', () => {
    const parsed = parseReadingGuide('## 표기 사전\n- **NA** (p.4): 개구수예요.\n- **λ**: 파장이에요.');
    expect(dictionaryTerms(parsed)).toEqual([{ term: 'NA', korean: '', definition: '개구수예요.',
      scope: 'legacy', page: 4 }]);
  });

  it('rejects incomplete definitions and bounds the dictionary without padding it', () => {
    const parsed = parseReadingGuide(`## 용어 사전\n- **bad**: 번역 | | 논문\n- **guess**: 추측 | 뜻 | 불명\n`
      + Array.from({ length: 110 }, (_, i) => `- **term ${i}**: 용어 ${i} | 설명 ${i}. | 분야 기본`).join('\n'));
    expect(dictionaryTerms(parsed)).toHaveLength(100);
    expect(dictionaryTerms(parsed).some(t => t.term === 'bad' || t.term === 'guess')).toBe(false);
  });
});
