// ---------------------------------------------------------------------------
// Citation detection — turns plain-text references inside chat answers into
// clickable jump targets (page / figure / table). Frontend-only, no backend
// metadata: we pattern-match the agent's prose.
//
// Supported forms (case-insensitive for the Latin tokens):
//   page   →  "p. 5", "p.5", "page 5", "페이지 5"
//   figure →  "Fig. 3", "Fig 3", "Figure 3", "그림 3"
//   table  →  "Table 2", "표 2"
// ---------------------------------------------------------------------------

export type CitationType = 'page' | 'figure' | 'table';

export interface CitationMatch {
  /** The exact matched substring, e.g. "Fig. 3" — used as the chip label. */
  raw: string;
  type: CitationType;
  /** The referenced integer (page / figure / table number). */
  n: number;
  start: number;
  end: number;
}

// Five capture groups, one integer per alternative, so the matched branch is
// identified by which group is populated:
//   1: page      2: figure(latin)  3: figure(그림)  4: table  5: table(표)
// Korean tokens use a negative lookbehind so "발표 3" does not match "표 3".
const CITATION_SOURCE =
  '(?:\\bp\\.\\s?|\\bpages?\\s+|(?<![가-힣])페이지\\s?)(\\d+)' +
  '|(?:\\bfig\\.?\\s?|\\bfigures?\\s+)(\\d+)' +
  '|(?<![가-힣])그림\\s?(\\d+)' +
  '|(?:\\btable\\s+)(\\d+)' +
  '|(?<![가-힣])표\\s?(\\d+)';

/** Detect every citation occurrence in `text`, left-to-right, non-overlapping. */
export function detectCitations(text: string): CitationMatch[] {
  const re = new RegExp(CITATION_SOURCE, 'gi');
  const out: CitationMatch[] = [];
  let m: RegExpExecArray | null;

  while ((m = re.exec(text)) !== null) {
    // Guard against a zero-width match locking the loop.
    if (m.index === re.lastIndex) {
      re.lastIndex += 1;
      continue;
    }

    let type: CitationType;
    let numStr: string | undefined;
    if (m[1]) {
      type = 'page';
      numStr = m[1];
    } else if (m[2] || m[3]) {
      type = 'figure';
      numStr = m[2] || m[3];
    } else {
      type = 'table';
      numStr = m[4] || m[5];
    }

    if (!numStr) continue;
    out.push({
      raw: m[0],
      type,
      n: parseInt(numStr, 10),
      start: m.index,
      end: m.index + m[0].length,
    });
  }

  return out;
}
