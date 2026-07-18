// 분석 마크다운에서 섹션 목차(ToC)를 뽑는 순수 유틸. ATX 헤딩(# ~ ######)만
// 인식하고, 코드펜스(``` / ~~~) 안의 헤딩은 무시한다. 렌더 단계에서 이 slug를
// 섹션 앵커 id로 써서 목차 점프·접기에 쓴다.

export interface OutlineItem {
  /** 헤딩 레벨(1~6). 분석 본문은 보통 2~3을 섹션으로 쓴다. */
  level: number;
  /** 강조 마커를 벗긴 헤딩 텍스트. */
  text: string;
  /** 앵커 id(중복 시 -2, -3 …). */
  slug: string;
}

const HEADING = /^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$/;
const EMPHASIS = /(\*\*|__|\*|_|`)/g;
const FENCE = /^\s*(```|~~~)/;

// \p{L}/\p{N}으로 한글 등 비ASCII 글자를 보존한다(ASCII-only \w는 한글을 날림).
export function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^\p{L}\p{N}]+/gu, '-')
      .replace(/^-+|-+$/g, '') || 'section'
  );
}

export function extractOutline(md: string): OutlineItem[] {
  const items: OutlineItem[] = [];
  const seen = new Map<string, number>();
  let inFence = false;

  for (const line of md.split('\n')) {
    if (FENCE.test(line)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;

    const m = HEADING.exec(line);
    if (!m) continue;

    const level = m[1].length;
    const text = m[2].replace(EMPHASIS, '').trim();
    const base = slugify(text);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    const slug = count > 0 ? `${base}-${count + 1}` : base;

    items.push({ level, text, slug });
  }

  return items;
}
