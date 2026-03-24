import type { ReactNode } from 'react';

interface PageScaffoldProps {
  children: ReactNode;
}

export default function PageScaffold({ children }: PageScaffoldProps) {
  return (
    <div className="h-full overflow-y-auto bg-surface-900 [.light_&]:bg-surface-50">
      {children}
    </div>
  );
}
