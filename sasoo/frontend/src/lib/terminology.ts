import type { ReadingGuide, TerminologyEntry } from './readingGuide';

export function dictionaryTerms(guide: ReadingGuide | null): TerminologyEntry[] {
  if (!guide) return [];
  const entries: TerminologyEntry[] = guide.terminology.length ? guide.terminology : guide.glossary.map(entry => ({
    term: entry.symbol, korean: '', definition: entry.meaning, scope: 'legacy', page: entry.page,
  }));
  const unique = new Map<string, TerminologyEntry>();
  for (const entry of entries) {
    if (!/[A-Za-z]{2}/.test(entry.term) || /[가-힣\\$^{}<>]/.test(entry.term)
      || entry.term.length > 120 || !entry.definition.trim()) continue;
    const key = entry.term.toLowerCase();
    if (!unique.has(key) || entry.scope === 'paper') unique.set(key, entry);
  }
  return [...unique.values()].slice(0, 100);
}

export interface TermMatch { start: number; end: number; entry: TerminologyEntry }

export function matchTerms(text: string, entries: readonly TerminologyEntry[]): TermMatch[] {
  const aliases = new Map<string, { spelling: string; entry: TerminologyEntry } | null>();
  for (const entry of entries) {
    const acronym = entry.term.match(/^(.+?)\s*\(([A-Z][A-Z0-9-]{1,14})\)$/);
    const names = acronym ? [entry.term, acronym[1], acronym[2]] : [entry.term];
    for (const spelling of names) {
      const key = spelling.toLowerCase();
      const previous = aliases.get(key);
      aliases.set(key, previous === null || (previous && previous.entry !== entry) ? null : { spelling, entry });
    }
  }
  const names = [...aliases.keys()].filter(name => aliases.get(name))
    .sort((a, b) => b.length - a.length);
  if (!names.length) return [];
  const pattern = new RegExp(names.map(name => name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'gi');
  const matches: TermMatch[] = [];
  for (const match of text.matchAll(pattern)) {
    const start = match.index;
    const end = start + match[0].length;
    if (/[A-Za-z0-9_]/.test(text[start - 1] ?? '') || /[A-Za-z0-9_]/.test(text[end] ?? '')) continue;
    const candidate = aliases.get(match[0].toLowerCase());
    if (!candidate || (/^[A-Z][A-Z0-9-]{1,14}$/.test(candidate.spelling) && match[0] !== candidate.spelling)) continue;
    matches.push({ start, end, entry: candidate.entry });
  }
  return matches;
}
