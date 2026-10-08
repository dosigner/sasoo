import { useRef, type ReactNode } from 'react';
import * as Dialog from '@radix-ui/react-dialog';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  title: string;
  maxWidth?: string;
}

export default function Modal({ open, onClose, children, title, maxWidth = 'max-w-md' }: ModalProps) {
  const openerRef = useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm animate-fade-in" />
        <Dialog.Content
          className={`fixed left-1/2 top-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] ${maxWidth} overflow-y-auto wrap-anywhere border border-border bg-surface p-6 shadow-lg rounded-surface animate-modal-slide-up focus:outline-hidden`}
          onOpenAutoFocus={() => {
            openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
          }}
          onCloseAutoFocus={(event) => {
            if (openerRef.current?.isConnected) {
              event.preventDefault();
              openerRef.current.focus();
            }
          }}
        >
          <Dialog.Title asChild>
            <span className="sr-only">{title}</span>
          </Dialog.Title>
          <Dialog.Description asChild>
            <span className="sr-only" />
          </Dialog.Description>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
