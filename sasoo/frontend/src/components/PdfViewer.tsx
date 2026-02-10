import { useState, useEffect } from 'react';
import { Viewer } from '@react-pdf-viewer/core';
import { defaultLayoutPlugin } from '@react-pdf-viewer/default-layout';
import { GlobalWorkerOptions } from 'pdfjs-dist';
import {
  FileText,
  Loader2,
  AlertCircle,
} from 'lucide-react';

// Import styles
import '@react-pdf-viewer/core/lib/styles/index.css';
import '@react-pdf-viewer/default-layout/lib/styles/index.css';

// Import worker as URL for bundling
import PdfWorker from 'pdfjs-dist/build/pdf.worker.min.js?url';

// Set worker globally
GlobalWorkerOptions.workerSrc = PdfWorker;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PdfViewerProps {
  /** URL to serve the PDF */
  pdfUrl: string;
  /** Paper title for display */
  title?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PdfViewer({ pdfUrl, title }: PdfViewerProps) {
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Create plugin instance
  const defaultLayoutPluginInstance = defaultLayoutPlugin({
    sidebarTabs: (defaultTabs) => [defaultTabs[0]], // Only show thumbnails
  });

  // Reset state when URL changes
  useEffect(() => {
    setIsLoading(true);
    setLoadError(null);
  }, [pdfUrl]);

  return (
    <div className="flex flex-col h-full bg-surface-900">
      {/* Header */}
      {title && (
        <div className="flex items-center gap-2 px-3 py-2 bg-surface-800 border-b border-surface-700 shrink-0">
          <FileText className="w-4 h-4 text-surface-400 shrink-0" />
          <span className="text-xs text-surface-300 truncate">{title}</span>
        </div>
      )}

      {/* PDF Viewer */}
      <div className="flex-1 relative overflow-hidden">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-900/80 z-10">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 text-primary-400 animate-spin" />
              <span className="text-sm text-surface-400">Loading PDF...</span>
            </div>
          </div>
        )}

        {loadError && (
          <div className="absolute inset-0 flex items-center justify-center bg-surface-900 z-10">
            <div className="flex flex-col items-center gap-3 text-center px-8">
              <AlertCircle className="w-10 h-10 text-red-400" />
              <div>
                <p className="text-sm text-surface-300 mb-1">
                  Unable to load PDF
                </p>
                <p className="text-xs text-surface-500">{loadError}</p>
              </div>
              <button
                onClick={() => {
                  setLoadError(null);
                  setIsLoading(true);
                }}
                className="btn-secondary text-xs mt-2"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        <div className="h-full [&_.rpv-core__viewer]:h-full">
          <Viewer
            fileUrl={pdfUrl}
            plugins={[defaultLayoutPluginInstance]}
            onDocumentLoad={() => {
              setIsLoading(false);
              setLoadError(null);
            }}
            renderError={(error) => {
              setIsLoading(false);
              setLoadError(error.message || 'Failed to load PDF');
              return <div />;
            }}
            theme={{
              theme: 'dark',
            }}
          />
        </div>
      </div>
    </div>
  );
}
