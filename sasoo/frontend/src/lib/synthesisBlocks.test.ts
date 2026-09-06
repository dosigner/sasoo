import { describe, it, expect } from 'vitest';

import { assignBlocks, formatMetricValue, pickReproRows } from './synthesisBlocks';
import type { VisualizationItem } from '@/lib/api';

function makeItem(overrides: Partial<VisualizationItem> & { id: number }): VisualizationItem {
  return {
    title: `item-${overrides.id}`,
    tool: 'mermaid',
    diagram_type: 'flowchart',
    description: '',
    category: '',
    mermaid_code: null,
    image_url: null,
    image_path: null,
    status: 'completed',
    error_message: null,
    block: null,
    ...overrides,
  };
}

describe('assignBlocks', () => {
  it('block 없는 혼합 목록: paperbanana는 concept, comparison mermaid는 result, 그 외 mermaid는 method, mindmap은 버림', () => {
    const items: VisualizationItem[] = [
      makeItem({ id: 1, tool: 'paperbanana' }),
      makeItem({ id: 2, tool: 'mermaid', category: 'comparison' }),
      makeItem({ id: 3, tool: 'mermaid', category: 'procedure' }),
      makeItem({ id: 4, tool: 'mermaid', diagram_type: 'mindmap' }),
    ];
    const assigned = assignBlocks(items);
    expect(assigned.concept?.id).toBe(1);
    expect(assigned.method.map((i) => i.id)).toEqual([3]);
    expect(assigned.result.map((i) => i.id)).toEqual([2]);
  });

  it('상한: method 4개면 3개만 남고, paperbanana 2개면 첫째만 concept가 된다', () => {
    const items: VisualizationItem[] = [
      makeItem({ id: 1, tool: 'paperbanana' }),
      makeItem({ id: 2, tool: 'paperbanana' }),
      makeItem({ id: 3, block: 'method' }),
      makeItem({ id: 4, block: 'method' }),
      makeItem({ id: 5, block: 'method' }),
      makeItem({ id: 6, block: 'method' }),
    ];
    const assigned = assignBlocks(items);
    expect(assigned.concept?.id).toBe(1);
    expect(assigned.method.map((i) => i.id)).toEqual([3, 4, 5]);
  });
});

describe('formatMetricValue', () => {
  it('unit이 "-"이거나 비면 value만, 그 외에는 "value unit"', () => {
    expect(formatMetricValue({ value: '42', unit: '-' })).toBe('42');
    expect(formatMetricValue({ value: '42', unit: '' })).toBe('42');
    expect(formatMetricValue({ value: '42', unit: 'dB' })).toBe('42 dB');
  });
});

describe('pickReproRows', () => {
  it('이름 불일치는 제거하고, 공백·대소문자 차이가 있어도 일치하는 행만 최대 5행 남긴다', () => {
    const recipe = {
      parameters: [
        { name: 'Learning Rate', value: '1e-4', unit: '-', notes: '' },
        { name: '  batch size ', value: '32', unit: '-', notes: '' },
        { name: 'Unrelated Param', value: '99', unit: '-', notes: '' },
        { name: 'p3', value: '1', unit: '-', notes: '' },
        { name: 'p4', value: '2', unit: '-', notes: '' },
        { name: 'p5', value: '3', unit: '-', notes: '' },
        { name: 'p6', value: '4', unit: '-', notes: '' },
      ],
    };
    const names = [
      { name: 'learning rate' },
      { name: 'Batch Size' },
      { name: 'p3' },
      { name: 'p4' },
      { name: 'p5' },
      { name: 'p6' },
    ];
    const { rows } = pickReproRows(recipe, names);
    expect(rows).toHaveLength(5);
    expect(rows.map((r) => r.name)).toEqual([
      'Learning Rate',
      '  batch size ',
      'p3',
      'p4',
      'p5',
    ]);
  });

  it('recipe가 null이거나 이름이 하나도 안 맞으면 빈 행을 반환한다', () => {
    expect(pickReproRows(null, [{ name: 'x' }]).rows).toEqual([]);
    const recipe = { parameters: [{ name: 'a', value: '1', unit: '-', notes: '' }] };
    expect(pickReproRows(recipe, [{ name: 'b' }]).rows).toEqual([]);
  });
});

describe('pickReproRows — showNotes', () => {
  it('notes가 하나라도 비어 있지 않으면 true, 전부 비어 있으면 false', () => {
    const withNotes = {
      parameters: [
        { name: 'a', value: '1', unit: '-', notes: '' },
        { name: 'b', value: '2', unit: '-', notes: '보정값 사용' },
      ],
    };
    expect(pickReproRows(withNotes, [{ name: 'a' }, { name: 'b' }]).showNotes).toBe(true);

    const withoutNotes = {
      parameters: [
        { name: 'a', value: '1', unit: '-', notes: '' },
        { name: 'b', value: '2', unit: '-', notes: '' },
      ],
    };
    expect(pickReproRows(withoutNotes, [{ name: 'a' }, { name: 'b' }]).showNotes).toBe(false);
  });
});
