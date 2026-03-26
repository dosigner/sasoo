import type { ReactNode } from 'react';

interface PageScaffoldProps {
  children: ReactNode;
  variant?: 'archive' | 'control' | 'default';
}

export default function PageScaffold({
  children,
  variant = 'default',
}: PageScaffoldProps) {
  const variantClass =
    variant === 'archive'
      ? 'page-scaffold-archive'
      : variant === 'control'
        ? 'page-scaffold-control'
        : 'page-scaffold-default';

  return (
    <div className={`page-scaffold ${variantClass}`}>
      {children}
    </div>
  );
}
