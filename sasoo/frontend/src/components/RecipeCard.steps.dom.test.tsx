// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import RecipeCard from './RecipeCard';

vi.mock('./amicro/CascadeIn', () => ({ default: ({ children }: { children: ReactNode }) => children }));
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  root = null;
  document.body.innerHTML = '';
});

it('renders ten experimental steps with one number each and preserves their content', () => {
  const text = [
    'CIFAR-10과 ImageNet을 32×32, 64×64, 128×128로 준비해.',
    '픽셀을 [-1,1]로 변환하고 ϕ(y)=2^7(y+1) 보정을 적용해.',
    '5-layer, 512-neuron MLP와 UNet을 구성해.',
    't를 U[0,1]에서 샘플링해.',
    '식 21의 x1−(1−σmin)x0 target을 계산해.',
    '같은 architecture와 epoch 수로 CFM loss를 최적화해.',
    'βmin=0.1, βmax=20으로 설정해.',
    'Adam을 β1=0.9, β2=0.999, ε=1e-8로 설정해.',
    '32-bit와 16-bit mixed precision을 적용해.',
    't∈[0,1]에서 ODE를 적분해 φ1(x0)를 얻어.',
  ];
  const container = document.createElement('div');
  document.body.appendChild(container);
  const mounted = createRoot(container);
  root = mounted;
  act(() => mounted.render(<RecipeCard recipe={{
    paper_id: 1, model_used: null, created_at: null,
    recipe: { title: 'Flow Matching', steps: text.map((step, index) => `${index + 1}. ${step}`) },
  }} />));
  const items = [...container.querySelectorAll('ol > li')];
  expect(items).toHaveLength(10);
  expect(items.map((item) => item.textContent)).toEqual(text.map((step, index) => `${index + 1}.${step}`));
  expect(items[0].textContent).not.toContain('1.1.');
  expect(items[9].textContent).not.toContain('10.10.');
});
