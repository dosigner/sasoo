// LLM 응답의 \(...\)·\[...\] 델리미터를 remark-math가 인식하는 $...$·$$...$$로
// 바꾼다. CommonMark가 파싱 과정에서 \(·\[ 백슬래시 이스케이프를 소비하므로,
// mdast 변환 플러그인이 아니라 파싱 전 원문 문자열에서 처리해야 한다.
// 코드펜스·인라인 코드 내부는 코드 예제가 깨지지 않도록 보호한다.

// 코드펜스(``` ... ```)와 인라인 코드(` ... `)를 토큰으로 분리한다.
// 캡처 그룹을 쓰므로 split 결과에 구분자(코드)가 그대로 포함된다.
const CODE_SPLIT = /(```[\s\S]*?```|`[^`\n]*`)/g;

// 짝이 맞는 델리미터 사이를 non-greedy로 매칭.
const DISPLAY = /\\\[([\s\S]+?)\\\]/g;
const INLINE = /\\\(([\s\S]+?)\\\)/g;

function convertSegment(text: string): string {
  // display를 먼저 처리(더 긴 델리미터 우선).
  // 치환은 함수 형태로 작성한다 — replace 문자열에서 $$는 리터럴 $ 로 해석되어
  // 개수 오류를 내기 때문.
  return text
    .replace(DISPLAY, (_match, inner) => `$$${inner}$$`)
    .replace(INLINE, (_match, inner) => `$${inner}$`);
}

export function normalizeMathDelimiters(md: string): string {
  return md
    .split(CODE_SPLIT)
    .map((part) => {
      // 코드 토큰(```...``` 또는 `...`)은 그대로 둔다.
      if (part.startsWith('```') || (part.startsWith('`') && part.endsWith('`'))) {
        return part;
      }
      return convertSegment(part);
    })
    .join('');
}
