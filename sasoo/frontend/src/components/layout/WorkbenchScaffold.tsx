import type { ReactNode } from 'react';

interface WorkbenchScaffoldProps {
  children: ReactNode;
}

export default function WorkbenchScaffold({ children }: WorkbenchScaffoldProps) {
  return (
    <div className="h-full bg-bg text-fg-secondary">
      {children}
    </div>
  );
}
