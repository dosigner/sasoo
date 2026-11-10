import { createContext, useContext } from 'react';
import type { UseReadingGuideResult } from '@/hooks/useReadingGuide';
import type { TerminologyEntry } from './readingGuide';

export const ReadingGuideContext = createContext<UseReadingGuideResult | null>(null);
export const TerminologyContext = createContext<readonly TerminologyEntry[]>([]);

export function useSharedReadingGuide() {
  const guide = useContext(ReadingGuideContext);
  if (!guide) throw new Error('ReadingGuideProvider is required');
  return guide;
}
