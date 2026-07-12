import type { ReactElement, ReactNode } from 'react';
import * as RadixTooltip from '@radix-ui/react-tooltip';

export interface TooltipProps {
  children: ReactElement;
  content: ReactNode;
  side?: RadixTooltip.TooltipContentProps['side'];
  className?: string;
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <RadixTooltip.Provider delayDuration={300} skipDelayDuration={600}>{children}</RadixTooltip.Provider>;
}

export default function Tooltip({ children, content, side = 'top', className = '' }: TooltipProps) {
  return (
    <RadixTooltip.Root delayDuration={300}>
      <RadixTooltip.Trigger asChild>{children}</RadixTooltip.Trigger>
      <RadixTooltip.Portal>
        <RadixTooltip.Content
          side={side}
          sideOffset={6}
          className={`z-50 border border-border bg-surface px-2 py-1 text-2xs text-fg shadow-lg rounded-control animate-fade-in data-[state=instant-open]:animate-none ${className}`}
        >
          {content}
          <RadixTooltip.Arrow className="fill-surface" />
        </RadixTooltip.Content>
      </RadixTooltip.Portal>
    </RadixTooltip.Root>
  );
}
