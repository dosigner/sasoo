import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { chatWithAgent, generateFigureExplanation } from './api';

const result = {
  paper_id: 7, figure_id: 1, figure_num: 'Figure 1', caption: 'Caption',
  explanation: '## 그림 개요\n측정 시간 10 ms', model_used: 'gpt-6-luna',
  tokens_in: 100, tokens_out: 50, cost_usd: 0.000035, tokens_cached: 20,
};
const encoder = new TextEncoder();

function streamResponse() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const response = new Response(new ReadableStream<Uint8Array>({ start(value) { controller = value; } }));
  return {
    response,
    send(data: object) { controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`)); },
    controller,
  };
}

beforeEach(() => {
  vi.stubGlobal('window', { location: { protocol: 'http:' } });
});
afterEach(() => vi.unstubAllGlobals());

it('shares one request and replays partial text to a returning reader before completion', async () => {
  const stream = streamResponse();
  const fetch = vi.fn().mockResolvedValue(stream.response);
  vi.stubGlobal('fetch', fetch);
  const firstProgress = vi.fn();
  const first = generateFigureExplanation('7', 1, firstProgress);
  stream.send({ type: 'token', content: '## 그림 개요\n' });
  await vi.waitFor(() => expect(firstProgress).toHaveBeenCalledWith('## 그림 개요\n'));
  const secondProgress = vi.fn();
  const second = generateFigureExplanation('7', 1, secondProgress);
  expect(secondProgress).toHaveBeenCalledWith('## 그림 개요\n');
  expect(fetch).toHaveBeenCalledTimes(1);
  stream.send({ type: 'token', content: '측정 시간 10 ms' });
  stream.send({ type: 'done', result });
  const responses = await Promise.all([first, second]);
  expect(responses).toEqual([result, result]);
  expect(secondProgress).toHaveBeenLastCalledWith(result.explanation);
  expect(fetch.mock.calls[0][0]).toBe('/api/analysis/7/figures/1/explain/stream');
});

it('decodes split Korean bytes and a final event without a trailing newline', async () => {
  const stream = streamResponse();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(stream.response));
  const progress = vi.fn();
  const pending = generateFigureExplanation('7', 1, progress);
  const bytes = encoder.encode(`data: ${JSON.stringify({ type: 'token', content: '측정' })}\n\n`);
  for (const byte of bytes) stream.controller.enqueue(new Uint8Array([byte]));
  stream.controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: 'done', result })}`));
  stream.controller.close();
  expect(await pending).toEqual(result);
  expect(progress).toHaveBeenCalledWith('측정');
});

it('rejects a missing completion and releases the request so a retry can succeed', async () => {
  const failed = streamResponse();
  const retry = streamResponse();
  const fetch = vi.fn().mockResolvedValueOnce(failed.response).mockResolvedValueOnce(retry.response);
  vi.stubGlobal('fetch', fetch);
  const pending = generateFigureExplanation('7', 1);
  failed.send({ type: 'token', content: '부분 설명' });
  failed.controller.close();
  await expect(pending).rejects.toThrow('완료되기 전에');
  const next = generateFigureExplanation('7', 1);
  retry.send({ type: 'done', result });
  expect(await next).toEqual(result);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('rejects SSE errors, malformed JSON and a completion for a different figure', async () => {
  for (const body of [
    `data: ${JSON.stringify({ type: 'error', message: '사용량 미확인' })}\n\n`,
    'data: {broken}\n\n',
    `data: ${JSON.stringify({ type: 'done', result: { ...result, figure_id: 2 } })}\n\n`,
  ]) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)));
    await expect(generateFigureExplanation('7', 1)).rejects.toThrow();
  }
});

it('keeps chat token and done callbacks working through the shared SSE reader', async () => {
  const body = [
    { type: 'token', content: '채팅 답변' },
    { type: 'done', tokens_in: 10, tokens_out: 5, cost_usd: 0.1 },
  ].map((data) => `data: ${JSON.stringify(data)}\n\n`).join('');
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)));
  const token = vi.fn();
  const done = vi.fn();
  await chatWithAgent('7', '질문', [], token, done);
  expect(token).toHaveBeenCalledWith('채팅 답변');
  expect(done).toHaveBeenCalledWith({ tokens_in: 10, tokens_out: 5, cost_usd: 0.1 });
});
