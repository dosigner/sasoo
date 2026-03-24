import type { ReactNode } from 'react';

interface WorkbenchScaffoldProps {
  children: ReactNode;
}

export default function WorkbenchScaffold({ children }: WorkbenchScaffoldProps) {
  return (
    <div className="h-full bg-surface-950 text-surface-200 [.light_&]:bg-surface-100">
      {children}
    </div>
  );
}
