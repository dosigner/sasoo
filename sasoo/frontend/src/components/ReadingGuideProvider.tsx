import { useMemo, type ReactNode } from 'react';
import { useReadingGuide } from '@/hooks/useReadingGuide';
import { ReadingGuideContext, TerminologyContext } from '@/lib/readingGuideContext';
import { dictionaryTerms } from '@/lib/terminology';

export default function ReadingGuideProvider({ paperId, level, field, children }: {
  paperId: string | null;
  level?: string | null;
  field?: string | null;
  children: ReactNode;
}) {
  const state = useReadingGuide(paperId, level, field);
  const terms = useMemo(() => dictionaryTerms(state.guide), [state.guide]);
  return <ReadingGuideContext.Provider value={state}>
    <TerminologyContext.Provider value={terms}>{children}</TerminologyContext.Provider>
  </ReadingGuideContext.Provider>;
}
