// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import type { VisualizationItem } from '@/lib/api';
import { DiagramLightbox, type LightboxTarget } from './DiagramLightbox';

// React 19: act() 경고를 끄고 갱신을 동기적으로 흘려보낸다.
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// 개념도(이미지) 항목만 쓴다. Mermaid 항목은 렌더러를 lazy import해 jsdom에서 돌리기 무겁다.
const concept = (id: number): VisualizationItem => ({
  id,
  title: `개념도 ${id}`,
  tool: 'paperbanana',
  diagram_type: 'flowchart',
  description: '',
  category: '',
  mermaid_code: null,
  image_url: `/static/library/p/paperbanana/${id}.png`,
  image_path: null,
  status: 'completed',
  error_message: null,
  block: 'concept',
});
const targets: LightboxTarget[] = [
  { item: concept(1), blockLabel: '방법 흐름' },
  { item: concept(2), blockLabel: '방법 흐름' },
];

const mounted: { root: Root; container: HTMLElement }[] = [];
function mount(index: number, onClose = vi.fn(), onIndexChange = vi.fn()) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <DiagramLightbox
        targets={targets}
        index={index}
        paperId={7}
        onClose={onClose}
        onIndexChange={onIndexChange}
        makeRepairHandler={() => async () => null}
      />
    );
  });
  mounted.push({ root, container });
  return { root, onClose, onIndexChange };
}
const keydown = (target: EventTarget, key: string) =>
  act(() => {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
  });

afterEach(() => {
  for (const { root, container } of mounted.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
  document.body.innerHTML = '';
});

describe('DiagramLightbox 키보드와 포커스(스펙 §4)', () => {
  it('ESC로 닫히고, 닫히면 포커스가 열기 전 요소로 돌아간다', () => {
    const trigger = document.createElement('button');
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { root, onClose } = mount(0);
    const dialog = document.querySelector('[role="dialog"][aria-modal="true"]');
    expect(dialog).not.toBeNull();
    // 포커스 트랩이 모달 안 첫 버튼으로 포커스를 옮긴다.
    expect(dialog!.contains(document.activeElement)).toBe(true);

    keydown(document, 'Escape');
    expect(onClose).toHaveBeenCalledTimes(1);

    act(() => root.unmount());
    mounted.pop();
    expect(document.activeElement).toBe(trigger);
  });

  it('방향키로 이웃 다이어그램으로 옮기고 범위 밖에서는 멈춘다', () => {
    const { onIndexChange } = mount(0);
    expect(document.body.textContent).toContain('방법 흐름 1/2');

    keydown(window, 'ArrowLeft');
    expect(onIndexChange).not.toHaveBeenCalled();

    keydown(window, 'ArrowRight');
    expect(onIndexChange).toHaveBeenCalledWith(1);
  });
});
