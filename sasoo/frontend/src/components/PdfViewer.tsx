import { useEffect, useMemo, useRef, useState } from 'react';
import { BookOpen } from 'lucide-react';
import { type PdfNavigationRequest } from '@/lib/api';
import { S } from '@/lib/strings';
import { ContentState } from '@/components/ui';

interface PdfViewerProps {
  pdfUrl: string;
  title?: string;
  navigationRequest?: PdfNavigationRequest | null;
  onPageChange?: (page: number) => void;
}

type FitMode = 'width' | 'page';

function buildPdfSrc(pdfUrl: string, page: number, fitMode: FitMode, reloadNonce: number): string {
  const baseUrl = pdfUrl.split('#')[0];
  const zoom = fitMode === 'width' ? 'page-width' : 'page-fit';
  return `${baseUrl}#page=${Math.max(page, 1)}&zoom=${zoom}&view=FitH&toolbar=1&navpanes=0&_reload=${reloadNonce}`;
}

export default function PdfViewer({
  pdfUrl,
  title,
  navigationRequest,
  onPageChange,
}: PdfViewerProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoaded, setIsLoaded] = useState(false);
  const lastNavigationId = useRef<string | null>(null);

  useEffect(() => {
    setCurrentPage(1);
    setIsLoaded(false);
    lastNavigationId.current = null;
  }, [pdfUrl]);

  useEffect(() => {
    if (!navigationRequest) return;
    if (lastNavigationId.current === navigationRequest.requestId) return;
    lastNavigationId.current = navigationRequest.requestId;
    setCurrentPage(Math.max(navigationRequest.page, 1));
  }, [navigationRequest]);

  useEffect(() => {
    onPageChange?.(currentPage);
  }, [currentPage, onPageChange]);

  const viewerSrc = useMemo(
    () => buildPdfSrc(pdfUrl, currentPage, 'width', 0),
    [currentPage, pdfUrl],
  );

  return (
    <div className="flex h-full flex-col bg-surface-950">
      <div className="relative min-h-0 flex-1 bg-[#09090b]">
        {!isLoaded && (
          <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
            <ContentState
              icon={BookOpen}
              title={S.pdf.loading}
              description="문서 뷰어를 준비하고 있습니다."
              loading
              tone="muted"
            />
          </div>
        )}

        <iframe
          key={viewerSrc}
          title={title || 'PDF viewer'}
          src={viewerSrc}
          className="h-full w-full border-0 bg-[#09090b]"
          onLoad={() => setIsLoaded(true)}
        />

        <noscript>
          <div className="flex h-full items-center justify-center p-6">
            <ContentState
              icon={BookOpen}
              title={S.pdf.loadFailed}
              description="PDF 보기를 위해 JavaScript가 필요합니다."
              tone="error"
            />
          </div>
        </noscript>
      </div>
    </div>
  );
}
