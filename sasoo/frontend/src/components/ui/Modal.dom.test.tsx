// @vitest-environment jsdom
import { act, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import Modal from './Modal';
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
it('names the dialog and returns Escape focus to its opener', async () => {
  function Example() {
    const [open, setOpen] = useState(false);
    return <><button onClick={() => setOpen(true)}>Open</button>
      <Modal open={open} onClose={() => setOpen(false)} title="논문 삭제 확인">
        <button onClick={() => setOpen(false)}>Close</button>
      </Modal></>;
  }
  const node = document.createElement('div');
  document.body.appendChild(node);
  const root = createRoot(node);
  await act(async () => root.render(<Example />));
  const opener = node.querySelector('button')!;
  opener.focus();
  await act(async () => opener.click());
  const dialog = document.querySelector('[role="dialog"]')!;
  expect(document.getElementById(dialog.getAttribute('aria-labelledby')!)?.textContent).toBe('논문 삭제 확인');
  await act(async () => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(document.activeElement).toBe(opener);
  act(() => root.unmount());
  node.remove();
});
