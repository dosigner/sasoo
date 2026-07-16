// LLM 응답의 \(...\)·\[...\] 델리미터를 remark-math가 인식하는 $...$·$$...$$로
// 바꾼다. CommonMark가 파싱 과정에서 \(·\[ 백슬래시 이스케이프를 소비하므로,
// mdast 변환 플러그인이 아니라 파싱 전 원문 문자열에서 처리해야 한다.
// 코드펜스·인라인 코드 내부는 코드 예제가 깨지지 않도록 보호한다.

// 코드펜스(``` ... ```)와 인라인 코드(` ... `)를 토큰으로 분리한다.
// 캡처 그룹을 쓰므로 split 결과에 구분자(코드)가 그대로 포함된다.
//
// 인라인 코드는 한 줄로 제한한다(`[^`\n]*`). CommonMark 자체는 단일 백틱
// 코드 스팬이 여러 줄에 걸치는 것을 허용하지만, 여기서는 의도적으로 배제한다:
// 분석 출력에서 여러 줄 코드는 LLM이 거의 항상 삼중 백틱 펜스로 쓰고(이미 보호됨),
// 개행을 허용하면 산문에 흩어진 단일 백틱 두 개 사이의 진짜 수식을 통째로
// "코드 스팬"으로 삼켜 변환을 건너뛰는 더 흔한 오작동이 생긴다. 여러 줄 단일
// 백틱 스팬 안에 LaTeX가 들어가는 극단 사례(비변환 대신 변환됨)는 이 트레이드오프로
// 감수한다. 다운스트림 react-markdown이 실제 CommonMark 파서다.
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
