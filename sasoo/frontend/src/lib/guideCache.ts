/**
 * 읽기 안내 로컬 캐시. 논문 하나당 마크다운 하나를 IndexedDB에 담아, 다시 열 때
 * 토큰을 쓰지 않게 한다. `papers.notes`(사용자 메모)는 건드리지 않는다.
 */

export interface GuideRecord {
  markdown: string;
  createdAt: number;
  level: string | null;
  costUsd: number | null;
}

export interface GuideStorage {
  get(paperId: string): Promise<GuideRecord | null>;
  set(paperId: string, value: GuideRecord): Promise<void>;
  delete(paperId: string): Promise<void>;
}

const DB_NAME = 'sasoo-reading-guide';
const STORE_NAME = 'guides';

export function createMemoryStorage(): GuideStorage {
  const map = new Map<string, GuideRecord>();
  return {
    async get(paperId) {
      return map.get(paperId) ?? null;
    },
    async set(paperId, value) {
      map.set(paperId, value);
    },
    async delete(paperId) {
      map.delete(paperId);
    },
  };
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(STORE_NAME)) {
        request.result.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('indexedDB blocked'));
  });
}

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

/**
 * IndexedDB를 쓰되, 없거나 열지 못하면 같은 API의 메모리 저장소로 조용히 내려간다
 * (프라이빗 모드, 저장소 차단 등). 실패는 한 번만 판정하고 이후엔 폴백을 재사용한다.
 */
function createIndexedDbStorage(): GuideStorage {
  const fallback = createMemoryStorage();
  let dbPromise: Promise<IDBDatabase | null> | null = null;

  const getDb = (): Promise<IDBDatabase | null> => {
    if (typeof indexedDB === 'undefined') return Promise.resolve(null);
    if (!dbPromise) dbPromise = openDatabase().catch(() => null);
    return dbPromise;
  };

  const withStore = async <T>(
    mode: IDBTransactionMode,
    run: (store: IDBObjectStore) => IDBRequest<T>,
  ): Promise<{ ok: true; value: T } | { ok: false }> => {
    const db = await getDb();
    if (!db) return { ok: false };
    try {
      const store = db.transaction(STORE_NAME, mode).objectStore(STORE_NAME);
      return { ok: true, value: await requestToPromise(run(store)) };
    } catch {
      return { ok: false };
    }
  };

  return {
    async get(paperId) {
      const result = await withStore<GuideRecord | undefined>('readonly', (store) =>
        store.get(paperId),
      );
      if (!result.ok) return fallback.get(paperId);
      return result.value ?? null;
    },
    async set(paperId, value) {
      const result = await withStore('readwrite', (store) => store.put(value, paperId));
      if (!result.ok) await fallback.set(paperId, value);
    },
    async delete(paperId) {
      const result = await withStore('readwrite', (store) => store.delete(paperId));
      if (!result.ok) await fallback.delete(paperId);
    },
  };
}

export function createGuideCache(storage: GuideStorage = createIndexedDbStorage()) {
  return {
    getGuide: (paperId: string) => storage.get(paperId),
    setGuide: (paperId: string, value: GuideRecord) => storage.set(paperId, value),
    deleteGuide: (paperId: string) => storage.delete(paperId),
  };
}

export const { getGuide, setGuide, deleteGuide } = createGuideCache();
