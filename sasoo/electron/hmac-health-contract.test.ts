import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { PythonManager } from './python-manager';

const vectors = JSON.parse(readFileSync('contract-fixtures/hmac-vectors.json', 'utf8')) as {
  token: string; health: string;
};

afterEach(() => vi.unstubAllGlobals());

it('accepts the shared health proof and rejects a different token', async () => {
  const manager = new PythonManager({ backendPath: '/unused', port: 8000, isDev: false });
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ instance_proof: vectors.health }))));
  await expect(manager.checkHealth(vectors.token)).resolves.toBe(true);
  await expect(manager.checkHealth('wrong-token')).resolves.toBe(false);
});
