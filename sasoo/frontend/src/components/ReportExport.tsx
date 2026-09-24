import { useState } from 'react';
import { getAnalysisReport } from '@/lib/api';
import { S } from '@/lib/strings';

export default function ReportExport({ paperId }: { paperId: string }) {
  const [format, setFormat] = useState<'md' | 'html'>('md');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState('');

  async function exportReport() {
    setBusy(true);
    setFeedback('');
    try {
      const [report, { downloadReport }] = await Promise.all([
        getAnalysisReport(paperId), import('@/lib/reportExport'),
      ]);
      downloadReport(report, format);
      setFeedback(S.reportExport.started);
    } catch {
      setFeedback(S.reportExport.failed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 flex flex-wrap items-center gap-2 border-t border-border/45 pt-4">
      <select
        aria-label={S.reportExport.format}
        className="input min-h-8 w-auto text-sm"
        value={format}
        disabled={busy}
        onChange={(event) => setFormat(event.target.value === 'html' ? 'html' : 'md')}
      >
        <option value="md">Markdown</option>
        <option value="html">HTML</option>
      </select>
      <button type="button" className="btn-secondary min-h-8 text-sm" disabled={busy} onClick={() => void exportReport()}>
        {busy ? S.reportExport.exporting : S.reportExport.export}
      </button>
      <p role="status" className="w-full text-sm text-fg-secondary">{feedback}</p>
    </div>
  );
}
