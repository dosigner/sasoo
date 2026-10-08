// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { createMemoryRouter, Link, RouterProvider } from 'react-router';
import { expect, it, vi } from 'vitest';
import { SaveBar } from './SaveBar';
import { SegmentGroup } from './SettingPrimitives';
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
it('keeps unsaved input and supports immediate keyboard selection before navigation', async () => {
  function Form() {
    const [value, setValue] = useState('a');
    return <><Link to="/home">홈</Link>
      <SegmentGroup ariaLabel="숙련도" options={[{key:'a',label:'A'},{key:'b',label:'B'}]} value={value} onChange={setValue} />
      <SaveBar changeCount={value === 'a' ? 0 : 1} saving={false} onSave={vi.fn()} onDiscard={() => setValue('a')} />
    </>;
  }
  const router = createMemoryRouter([{path:'/',element:<Form />},{path:'/home',element:<p>Home</p>}]);
  const node = document.createElement('div'); document.body.appendChild(node);
  const root = createRoot(node);
  await act(async () => root.render(<RouterProvider router={router} />));
  const radios = node.querySelectorAll<HTMLButtonElement>('[role="radio"]');
  radios[0].focus();
  act(() => radios[0].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true})));
  expect(radios[1].getAttribute('aria-checked')).toBe('true');
  expect(document.activeElement).toBe(radios[1]);
  await act(async () => node.querySelector<HTMLAnchorElement>('a')!.click());
  expect(router.state.location.pathname).toBe('/');
  const keep = [...document.querySelectorAll('button')].find(b=>b.textContent==='계속 편집')!;
  await act(async () => keep.click());
  expect(radios[1].getAttribute('aria-checked')).toBe('true');
  await act(async () => node.querySelector<HTMLAnchorElement>('a')!.click());
  const leave = [...document.querySelectorAll('button')].find(b=>b.textContent==='저장하지 않고 이동')!;
  await act(async () => leave.click());
  expect(router.state.location.pathname).toBe('/home');
  act(() => root.unmount()); node.remove(); router.dispose();
});
