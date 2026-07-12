import * as RadixDropdownMenu from '@radix-ui/react-dropdown-menu';

const Root = RadixDropdownMenu.Root;
const Trigger = RadixDropdownMenu.Trigger;

function Content({
  className = '',
  sideOffset = 4,
  ...props
}: RadixDropdownMenu.DropdownMenuContentProps) {
  return (
    <RadixDropdownMenu.Portal>
      <RadixDropdownMenu.Content
        sideOffset={sideOffset}
        className={`z-50 min-w-[10rem] border border-border bg-surface p-1 shadow-lg rounded-surface animate-pop-in [transform-origin:var(--radix-dropdown-menu-content-transform-origin)] ${className}`}
        {...props}
      />
    </RadixDropdownMenu.Portal>
  );
}

function Item({ className = '', ...props }: RadixDropdownMenu.DropdownMenuItemProps) {
  return (
    <RadixDropdownMenu.Item
      className={`relative flex cursor-pointer select-none items-center rounded-control px-2.5 py-1.5 text-sm text-fg outline-none data-[highlighted]:bg-surface-hover data-[highlighted]:text-accent focus-visible:ring-2 focus-visible:ring-accent ${className}`}
      {...props}
    />
  );
}

function Separator({ className = '', ...props }: RadixDropdownMenu.DropdownMenuSeparatorProps) {
  return (
    <RadixDropdownMenu.Separator
      className={`my-1 h-px bg-border ${className}`}
      {...props}
    />
  );
}

export const DropdownMenu = {
  Root,
  Trigger,
  Content,
  Item,
  Separator,
};

export default DropdownMenu;
