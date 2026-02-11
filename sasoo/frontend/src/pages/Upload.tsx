import { useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Upload as UploadIcon,
  FileText,
  X,
  Check,
  Loader2,
  AlertCircle,
  ArrowRight,
  HardDrive,
  Beaker,
} from 'lucide-react';
import { uploadPaper, DOMAINS, type UploadResponse } from '@/lib/api';
import { getAgentMeta } from '@/lib/agents';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB
const ACCEPTED_TYPES = ['application/pdf'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

type UploadStage = 'idle' | 'uploading' | 'parsing' | 'classified' | 'error';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Upload() {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [stage, setStage] = useState<UploadStage>('idle');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [domainOverride, setDomainOverride] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // -----------------------------------------------------------------------
  // File validation
  // -----------------------------------------------------------------------
  const validateFile = useCallback((file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type) && !file.name.endsWith('.pdf')) {
      return 'Only PDF files are accepted.';
    }
    if (file.size > MAX_FILE_SIZE) {
      return `File too large. Maximum size is ${formatFileSize(MAX_FILE_SIZE)}.`;
    }
    if (file.size === 0) {
      return 'File appears to be empty.';
    }
    return null;
  }, []);

  // -----------------------------------------------------------------------
  // Handle file selection
  // -----------------------------------------------------------------------
  const handleFileSelect = useCallback(
    (file: File) => {
      const validationError = validateFile(file);
      if (validationError) {
        setError(validationError);
        return;
      }
      setSelectedFile(file);
      setError(null);
      setStage('idle');
      setUploadResult(null);
    },
    [validateFile]
  );

  // -----------------------------------------------------------------------
  // Upload handler
  // -----------------------------------------------------------------------
  const handleUpload = useCallback(async () => {
    if (!selectedFile) return;

    setError(null);
    setStage('uploading');
    setUploadProgress(0);

    try {
      const result = await uploadPaper(selectedFile, (progress) => {
        setUploadProgress(progress);
        if (progress >= 100) {
          setStage('parsing');
        }
      });

      setUploadResult(result);
      setDomainOverride(result.domain);
      setStage('classified');
    } catch (err) {
      setStage('error');
      setError(
        err instanceof Error ? err.message : 'Upload failed. Please try again.'
      );
    }
  }, [selectedFile]);

  // -----------------------------------------------------------------------
  // Navigate to workbench
  // -----------------------------------------------------------------------
  const handleStartAnalysis = useCallback(() => {
    if (uploadResult) {
      navigate(`/workbench/${uploadResult.id}`);
    }
  }, [navigate, uploadResult]);

  // -----------------------------------------------------------------------
  // Drag and drop handlers
  // -----------------------------------------------------------------------
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only set false if leaving the drop zone (not entering a child)
    if (e.currentTarget === e.target) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      const files = Array.from(e.dataTransfer.files);
      if (files.length > 0) {
        handleFileSelect(files[0]);
      }
    },
    [handleFileSelect]
  );

  // -----------------------------------------------------------------------
  // Clear selection
  // -----------------------------------------------------------------------
  const clearFile = useCallback(() => {
    setSelectedFile(null);
    setUploadResult(null);
    setStage('idle');
    setError(null);
    setUploadProgress(0);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  return (
    <div className="min-h-full flex items-center justify-center p-8">
      <div className="w-full max-w-xl">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-primary-500/10 border border-primary-500/20 flex items-center justify-center mx-auto mb-4">
            <Beaker className="w-7 h-7 text-primary-400" />
          </div>
          <h1 className="text-2xl font-bold text-surface-100 mb-2">
            Upload Paper
          </h1>
          <p className="text-sm text-surface-400 max-w-sm mx-auto">
            Upload an academic paper (PDF) for AI-powered analysis.
            We'll extract figures, parameters, and generate visual summaries.
          </p>
        </div>

        {/* Upload zone */}
        <div
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className={`relative border-2 border-dashed rounded-2xl p-8 text-center transition-all duration-200 ${
            isDragging
              ? 'border-primary-500 bg-primary-500/10 backdrop-blur-md scale-[1.02]'
              : selectedFile
                ? 'border-surface-600 bg-surface-800'
                : 'border-surface-600 bg-surface-800/50 hover:border-surface-500 hover:bg-surface-800'
          }`}
        >
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFileSelect(file);
            }}
          />

          {/* No file selected */}
          {!selectedFile && (
            <div className="space-y-4">
              <div className="w-12 h-12 rounded-xl bg-surface-700 border border-surface-600 flex items-center justify-center mx-auto">
                <UploadIcon className="w-6 h-6 text-surface-400" />
              </div>
              <div>
                <p className="text-sm text-surface-200 mb-1">
                  Drag and drop your PDF here
                </p>
                <p className="text-2xs text-surface-500">
                  or{' '}
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="text-primary-400 hover:text-primary-300 underline underline-offset-2"
                  >
                    browse files
                  </button>
                </p>
              </div>
              <div className="flex items-center justify-center gap-3 text-2xs text-surface-500">
                <span className="flex items-center gap-1">
                  <FileText className="w-3 h-3" />
                  PDF only
                </span>
                <span className="w-1 h-1 rounded-full bg-surface-600" />
                <span className="flex items-center gap-1">
                  <HardDrive className="w-3 h-3" />
                  Max {formatFileSize(MAX_FILE_SIZE)}
                </span>
              </div>
            </div>
          )}

          {/* File selected */}
          {selectedFile && (
            <div className="space-y-4">
              {/* File info */}
              <div className="flex items-center gap-3 bg-surface-700/50 rounded-lg px-4 py-3">
                <FileText className="w-8 h-8 text-primary-400 shrink-0" />
                <div className="flex-1 min-w-0 text-left">
                  <p className="text-sm text-surface-200 truncate">
                    {selectedFile.name}
                  </p>
                  <p className="text-2xs text-surface-500">
                    {formatFileSize(selectedFile.size)}
                  </p>
                </div>
                {stage === 'idle' && (
                  <button
                    onClick={clearFile}
                    className="p-1 rounded hover:bg-surface-600 text-surface-400 hover:text-surface-200 transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>

              {/* Upload progress */}
              {(stage === 'uploading' || stage === 'parsing') && (
                <div className="space-y-2">
                  <div className="h-2 bg-surface-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-500 rounded-full transition-all duration-300"
                      style={{
                        width:
                          stage === 'parsing'
                            ? '100%'
                            : `${uploadProgress}%`,
                      }}
                    />
                  </div>
                  <div className="flex items-center justify-center gap-2 text-xs text-surface-400">
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-primary-400" />
                    {stage === 'uploading'
                      ? `Uploading... ${uploadProgress}%`
                      : 'Parsing PDF and classifying domain...'}
                  </div>
                </div>
              )}

              {/* Classification result */}
              {stage === 'classified' && uploadResult && (
                <div className="space-y-4 fade-in-up">
                  <div className="flex items-center gap-2 text-sm text-emerald-400">
                    <Check className="w-4 h-4" />
                    Paper uploaded and parsed successfully
                  </div>

                  {/* Paper info */}
                  <div className="bg-surface-700/50 rounded-lg p-4 text-left space-y-3">
                    <div>
                      <span className="text-2xs text-surface-500 uppercase tracking-wider">
                        Title
                      </span>
                      <p className="text-sm text-surface-200 mt-0.5">
                        {uploadResult.title}
                      </p>
                    </div>
                    {/* Agent card */}
                    {(() => {
                      const agent = getAgentMeta(uploadResult.agent_used);
                      if (!agent) return null;
                      return (
                        <div className={`flex items-center gap-3 p-3 rounded-lg ${agent.bgColor} border ${agent.borderColor}`}>
                          <img
                            src={agent.image}
                            alt={agent.name}
                            className="w-16 h-16 rounded-lg object-cover shrink-0"
                          />
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className={`text-sm font-semibold ${agent.color}`}>
                                {agent.name}
                              </span>
                              <span className="text-2xs text-surface-500">
                                {agent.personality}
                              </span>
                            </div>
                            <p className="text-xs text-surface-400 mt-0.5 italic">
                              "{agent.quote}"
                            </p>
                          </div>
                        </div>
                      );
                    })()}

                    {/* Domain selection */}
                    <div>
                      <span className="text-2xs text-surface-500 uppercase tracking-wider">
                        Detected Domain
                      </span>
                      <select
                        value={domainOverride}
                        onChange={(e) => setDomainOverride(e.target.value)}
                        className="input mt-1"
                      >
                        {DOMAINS.map((domain) => (
                          <option key={domain.key} value={domain.key}>
                            {domain.label}
                            {domain.key === uploadResult.domain
                              ? ' (detected)'
                              : ''}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Start Analysis button */}
                  <button
                    onClick={handleStartAnalysis}
                    className="btn-primary w-full py-3 text-sm"
                  >
                    Open & Analyze
                    <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              )}

              {/* Error state */}
              {stage === 'error' && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm text-red-400">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                  </div>
                  <div className="flex gap-2">
                    <button onClick={handleUpload} className="btn-primary flex-1">
                      Retry
                    </button>
                    <button onClick={clearFile} className="btn-secondary">
                      Clear
                    </button>
                  </div>
                </div>
              )}

              {/* Upload button (idle state with file selected) */}
              {stage === 'idle' && (
                <button
                  onClick={handleUpload}
                  className="btn-primary w-full py-3 text-sm"
                >
                  <UploadIcon className="w-4 h-4" />
                  Upload Paper
                </button>
              )}
            </div>
          )}
        </div>

        {/* Error outside the drop zone */}
        {error && stage === 'idle' && (
          <div className="mt-4 flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-4 py-3">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
