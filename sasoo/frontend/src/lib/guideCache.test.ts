import { describe, expect, it } from 'vitest';

import { createGuideCache, createMemoryStorage, type GuideRecord } from './guideCache';

const RECORD: GuideRecord = {
  markdown: '## 표기 사전\n- **λ** (p.3): 파장이에요.',
  createdAt: 1_757_000_000_000,
  level: 'masters',
  costUsd: 0.012,
};

describe('createGuideCache (메모리 폴백)', () => {
  it('저장한 안내를 논문 id로 되찾는다', async () => {
    const cache = createGuideCache(createMemoryStorage());

    expect(await cache.getGuide('7')).toBeNull();
    await cache.setGuide('7', RECORD);
    expect(await cache.getGuide('7')).toEqual(RECORD);
  });

  it('삭제하면 없어지고 다른 논문에는 영향이 없다', async () => {
    const cache = createGuideCache(createMemoryStorage());

    await cache.setGuide('7', RECORD);
    await cache.setGuide('8', { ...RECORD, markdown: '다른 논문' });
    await cache.deleteGuide('7');

    expect(await cache.getGuide('7')).toBeNull();
    expect((await cache.getGuide('8'))?.markdown).toBe('다른 논문');
  });
});
