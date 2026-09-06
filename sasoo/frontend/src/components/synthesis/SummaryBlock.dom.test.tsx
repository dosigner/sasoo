// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { SynthesisResult } from '@/lib/api';
import { SummaryBlock } from './blocks';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const synthesis: SynthesisResult = {
  paper_id: 7,
  problem_sentence: '문제 한 문장',
  method_sentence: '방법 한 문장',
  key_metrics: [1, 2, 3, 4, 5].map((n) => ({
    label: `지표 ${n}`,
    value: String(n),
    unit: 'dB',
    evidence: `loss was ${n} dB`,
  })),
  equations: [],
  result_figures: [],
  key_parameters: [],
  equation_count: 0,
  dropped: {},
  model_used: null,
  cost_usd: null,
  created_at: null,
};

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
});

describe('SummaryBlock 핵심 수치 타일(스펙 §3.1, PR #43 칩 계약)', () => {
  it('타일은 최대 3개이고 칩 클래스를 쓰지 않는다', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => root!.render(<SummaryBlock synthesis={synthesis} />));

    const tiles = container.querySelectorAll('.text-xl.tabular-nums');
    expect(tiles.length).toBe(3);
    expect(Array.from(tiles).map((t) => t.textContent)).toEqual(['1 dB', '2 dB', '3 dB']);
    expect(container.querySelector('.badge, .chip, [class*="badge"]')).toBeNull();
    expect(container.textContent).toContain('문제 한 문장');
  });
});
