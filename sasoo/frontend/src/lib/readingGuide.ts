/**
 * 읽기 안내(Reading Guide)의 프롬프트와 파서.
 *
 * 질문 도우미 API를 한 번 호출해 고정 헤딩 3개짜리 마크다운을 받고, 그 마크다운을
 * 목록/카드/아코디언으로 나눠 렌더하기 위한 구조로 바꾼다. 형식이 어긋나면
 * `parsed: false`로 돌려주고 호출부가 raw 마크다운을 그대로 보여준다.
 */
import { S } from '@/lib/strings';

export interface GlossaryEntry {
  symbol: string;
  meaning: string;
  page: number | null;
}

export interface PrerequisiteEntry {
  name: string;
  primer: string;
  why: string | null;
}

export interface GuideSection {
  title: string;
  page: number | null;
  body: string;
}

export interface ReadingGuide {
  glossary: GlossaryEntry[];
  prerequisites: PrerequisiteEntry[];
  sections: GuideSection[];
  raw: string;
  parsed: boolean;
}

export const GUIDE_HEADINGS = {
  glossary: '표기 사전',
  prerequisites: '선행 지식',
  sections: '섹션별 직관',
} as const;

// ---------------------------------------------------------------------------
// Prompt
// ---------------------------------------------------------------------------

function levelLabel(level: string | null | undefined): string | null {
  if (!level) return null;
  const levels = S.levels as Record<string, { label: string } | undefined>;
  return levels[level]?.label ?? null;
}

/**
 * 안내 생성 프롬프트. 서버가 논문 전문을 붙이므로 본문은 넣지 않는다.
 * 출력 형식을 못 박아야 `parseReadingGuide`가 구조로 되돌릴 수 있다.
 */
export function buildReadingGuidePrompt(level: string | null | undefined): string {
  const label = levelLabel(level);
  const levelLine = label
    ? `읽는 사람은 ${label}이에요. 용어와 배경 설명을 그 눈높이에 맞춰 주세요.`
    : '읽는 사람은 이 분야가 처음인 연구자예요.';

  return [
    '이 논문을 처음 읽는 사람이 원문을 따라갈 수 있도록 읽기 안내를 만들어 주세요.',
    levelLine,
    '',
    '규칙',
    `1. 아래 세 개의 2단계 헤딩만 이 순서로 쓰고, 머리말이나 맺음말, 다른 헤딩은 쓰지 마세요.`,
    '2. 수식 유도는 쓰지 마세요. 무엇을 하려는지와 왜 그렇게 하는지, 직관만 씁니다.',
    '3. 페이지는 논문에 적힌 번호를 쓰고, 확실하지 않으면 괄호를 통째로 빼세요.',
    '4. 해요체로 쓰고, 줄임표나 화살표 기호는 쓰지 마세요.',
    '',
    `## ${GUIDE_HEADINGS.glossary}`,
    '논문에 나오는 기호와 약어를 10개에서 80개 사이로, 처음 정의된 순서대로 적어 주세요.',
    '각 항목은 다음 형식의 한 줄로만 씁니다.',
    '- **기호** (p.3): 뜻을 한 문장으로',
    '',
    `## ${GUIDE_HEADINGS.prerequisites}`,
    '논문이 설명 없이 전제하는 개념을 3개에서 6개 사이로 골라 주세요.',
    '각 항목은 다음 형식으로 씁니다.',
    '- **개념 이름**: 개념 자체를 2~3문장으로 설명해요. 이 논문에서: 이 개념이 왜 필요한지 한 문장.',
    '',
    `## ${GUIDE_HEADINGS.sections}`,
    '논문의 실제 섹션을 5개에서 12개 사이로, 원문 순서대로 다뤄 주세요.',
    '각 섹션은 3단계 헤딩 한 줄과 그 아래 한 단락으로 씁니다.',
    '### 섹션 제목 (p.5)',
    '그 섹션이 무엇을 하려는지, 왜 그 방법을 골랐는지 한 단락으로 씁니다.',
  ].join('\n');
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------

const MATH_OPEN_RE = /^\s*(?:\\\(|\\\[|\$\$?)\s*/;
const MATH_CLOSE_RE = /\s*(?:\\\)|\\\]|\$\$?)\s*$/;

/**
 * 표기 사전 기호를 PDF 본문 검색어로 바꾼다. 모델은 기호를 `\(p_t\)`처럼 수식으로 쓰는데,
 * 그 TeX 소스를 pdf.js에 넣으면 아무것도 안 잡힌다. 델리미터를 벗긴 뒤에도 명령이나
 * 첨자가 남으면 검색이 무의미하니 null을 돌려주고, 호출부는 페이지 이동만 한다.
 */
export function glossarySearchTerm(symbol: string): string | null {
  const bare = symbol.replace(MATH_OPEN_RE, '').replace(MATH_CLOSE_RE, '').trim();
  if (!bare || /[\\{}^_]/.test(bare)) return null;
  return bare;
}

/**
 * 괄호 안 페이지 표기. `(p.3)`, `(p. 3)`, `(페이지 3)`, `(3쪽)`을 모두 받는다.
 * 괄호 안이 숫자 하나로 끝나야 하므로 `(2D)` 같은 제목 괄호는 걸리지 않는다.
 */
const PAGE_RE = /\(\s*(?:p{1,2}\.?|page|페이지)?\s*(\d{1,4})\s*(?:쪽|페이지|p)?\s*\)/i;

const HEADING_RE = /^\s{0,3}#{1,6}\s+(.*)$/;
const BULLET_RE = /^\s*[-*+]\s+(.*)$/;
const BOLD_RE = /\*\*(.+?)\*\*/;
const WHY_RE = /이\s*논문에서(?:는)?\s*[:：]\s*/;

function extractPage(text: string): number | null {
  const match = text.match(PAGE_RE);
  if (!match) return null;
  const page = Number.parseInt(match[1], 10);
  return Number.isFinite(page) && page > 0 ? page : null;
}

function stripPage(text: string): string {
  return text.replace(PAGE_RE, ' ');
}

/** 헤딩 텍스트를 공백/강조/구두점 없는 형태로 눌러 비교한다. */
function normalizeHeading(text: string): string {
  return text.replace(/[*_`#:：.]/g, '').replace(/\s+/g, '');
}

const HEADING_KEYS: Record<string, 'glossary' | 'prerequisites' | 'sections'> = {
  [normalizeHeading(GUIDE_HEADINGS.glossary)]: 'glossary',
  [normalizeHeading(GUIDE_HEADINGS.prerequisites)]: 'prerequisites',
  [normalizeHeading(GUIDE_HEADINGS.sections)]: 'sections',
};

function tidy(text: string): string {
  return text.replace(/\s+/g, ' ').replace(/^[\s:：,.-]+/, '').replace(/[\s]+$/, '').trim();
}

function parseGlossaryLine(line: string): GlossaryEntry | null {
  const bullet = line.match(BULLET_RE);
  if (!bullet) return null;
  const body = bullet[1];
  const page = extractPage(body);
  const withoutPage = stripPage(body);

  const bold = withoutPage.match(BOLD_RE);
  let symbol: string;
  let meaning: string;
  if (bold && bold.index !== undefined) {
    symbol = tidy(bold[1]);
    meaning = tidy(withoutPage.slice(bold.index + bold[0].length));
  } else {
    const colon = withoutPage.indexOf(':');
    if (colon === -1) return null;
    symbol = tidy(withoutPage.slice(0, colon));
    meaning = tidy(withoutPage.slice(colon + 1));
  }

  if (!symbol) return null;
  return { symbol, meaning, page };
}

function parsePrerequisiteLine(line: string): PrerequisiteEntry | null {
  const bullet = line.match(BULLET_RE);
  if (!bullet) return null;
  const body = bullet[1];

  const bold = body.match(BOLD_RE);
  let name: string;
  let rest: string;
  if (bold && bold.index !== undefined) {
    name = tidy(bold[1]);
    rest = body.slice(bold.index + bold[0].length);
  } else {
    const colon = body.indexOf(':');
    if (colon === -1) return null;
    name = tidy(body.slice(0, colon));
    rest = body.slice(colon + 1);
  }

  if (!name) return null;

  const whyMatch = rest.match(WHY_RE);
  if (whyMatch && whyMatch.index !== undefined) {
    return {
      name,
      primer: tidy(rest.slice(0, whyMatch.index)),
      why: tidy(rest.slice(whyMatch.index + whyMatch[0].length)) || null,
    };
  }
  return { name, primer: tidy(rest), why: null };
}

export function parseReadingGuide(markdown: string): ReadingGuide {
  const raw = markdown ?? '';
  const buckets: Record<'glossary' | 'prerequisites' | 'sections', string[]> = {
    glossary: [],
    prerequisites: [],
    sections: [],
  };

  let current: keyof typeof buckets | null = null;
  let sawHeading = false;

  for (const line of raw.split('\n')) {
    const heading = line.match(HEADING_RE);
    if (heading) {
      const key = HEADING_KEYS[normalizeHeading(heading[1])];
      if (key) {
        current = key;
        sawHeading = true;
        continue;
      }
    }
    if (current) buckets[current].push(line);
  }

  const glossary = buckets.glossary
    .map(parseGlossaryLine)
    .filter((entry): entry is GlossaryEntry => entry !== null);

  const prerequisites = buckets.prerequisites
    .map(parsePrerequisiteLine)
    .filter((entry): entry is PrerequisiteEntry => entry !== null);

  const sections: GuideSection[] = [];
  for (const line of buckets.sections) {
    const heading = line.match(HEADING_RE);
    if (heading) {
      const title = tidy(stripPage(heading[1]).replace(/\*\*/g, ''));
      if (title) {
        sections.push({ title, page: extractPage(heading[1]), body: '' });
      }
      continue;
    }
    const open = sections[sections.length - 1];
    if (open) open.body += `${line}\n`;
  }
  for (const section of sections) {
    section.body = section.body.trim();
  }

  const parsed =
    sawHeading && glossary.length + prerequisites.length + sections.length > 0;

  return { glossary, prerequisites, sections, raw, parsed };
}
