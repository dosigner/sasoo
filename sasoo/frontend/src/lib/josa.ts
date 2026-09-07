// 앞말의 끝소리에 따라 "로"/"으로"를 붙인다. 모음이나 ㄹ 받침으로 끝나면 "로"(서울로, 이로),
// 그 밖의 받침으로 끝나면 "으로"(삼으로, 결론으로).
//
// citation 라벨(예: "Fig. 3", "표 6")처럼 숫자로 끝나는 텍스트는 한자어 숫자 읽기를 따른다.
// 1의 자리 발음: 0영 1일 2이 3삼 4사 5오 6육 7칠 8팔 9구. 이 중 "으로"를 받는 것은
// 영(ㅇ)·삼(ㅁ)·육(ㄱ)뿐이고, 일·칠·팔은 ㄹ 받침이라 "로"를 받는다.
// 두 자리 이상도 마지막 음절이 1의 자리 발음이므로(23→이십삼→삼, 20→이십→십) 같은 표로 충분하다.
const EURO_LAST_DIGIT = new Set(['0', '3', '6']);
const JONGSEONG_RIEUL = 8; // (code - 0xAC00) % 28 의 ㄹ 받침 인덱스

export function withRoJosa(text: string): string {
  const digitMatch = text.match(/(\d+)$/);
  let euro: boolean;
  if (digitMatch) {
    const lastDigit = digitMatch[1][digitMatch[1].length - 1];
    euro = EURO_LAST_DIGIT.has(lastDigit);
  } else {
    const code = (text[text.length - 1] ?? '').charCodeAt(0);
    const jong = code >= 0xac00 && code <= 0xd7a3 ? (code - 0xac00) % 28 : 0;
    euro = jong !== 0 && jong !== JONGSEONG_RIEUL;
  }
  return `${text}${euro ? '으로' : '로'}`;
}
