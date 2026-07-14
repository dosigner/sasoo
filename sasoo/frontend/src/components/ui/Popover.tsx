import * as RadixPopover from '@radix-ui/react-popover';

const Root = RadixPopover.Root;
const Trigger = RadixPopover.Trigger;
const Anchor = RadixPopover.Anchor;
const Close = RadixPopover.Close;

function Content({
  className = '',
  sideOffset = 8,
  ...props
}: RadixPopover.PopoverContentProps) {
  return (
    <RadixPopover.Portal>
      <RadixPopover.Content
        sideOffset={sideOffset}
        className={`z-50 border border-border bg-surface p-3 shadow-lg rounded-surface animate-pop-in [transform-origin:var(--radix-popover-content-transform-origin)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent ${className}`}
        {...props}
      />
    </RadixPopover.Portal>
  );
}

export const Popover = {
  Root,
  Trigger,
  Anchor,
  Close,
  Content,
};

export default Popover;
