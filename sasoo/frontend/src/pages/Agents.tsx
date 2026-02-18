import { useState, useEffect, useCallback, useRef } from 'react';
import { S } from '@/lib/strings';
import {
  getAgents, getAgent, createAgent, updateAgent, deleteAgent,
  duplicateAgent, toggleAgent, exportAgent, importAgent,
  type AgentDetail,
} from '@/lib/api';
import AgentAvatar from '@/components/AgentAvatar';
import {
  Plus, Upload, Download, Copy, Trash2, Edit3, Power, PowerOff,
  ChevronLeft, ChevronRight, Eye, Code, X, Check, AlertTriangle,
} from 'lucide-react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PageMode = 'list' | 'create' | 'edit';

interface AgentFormData {
  name: string;
  display_name: string;
  display_name_ko: string;
  personality: string;
  quote: string;
  color: string;
  domain: string;
  domain_display: string;
  domain_display_ko: string;
  keywords: string[];
  weighted_keywords: string[];
  recipe_parameters: string[];
  model: string;
  enabled: boolean;
  prompts: {
    screening: string;
    visual: string;
    recipe: string;
    deepdive: string;
  };
}

interface ToastState {
  message: string;
  type: 'success' | 'error';
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PRESET_COLORS = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#06b6d4', '#6366f1', '#a855f7', '#ec4899',
];

const WIZARD_STEPS = [
  { n: 1, label: S.agents.stepIdentity },
  { n: 2, label: S.agents.stepDomain },
  { n: 3, label: S.agents.stepParameters },
  { n: 4, label: S.agents.stepPrompts },
  { n: 5, label: S.agents.stepPreview },
];

const PROMPT_TABS = [
  { key: 'screening', label: S.agents.screening },
  { key: 'visual',    label: S.agents.visual },
  { key: 'recipe',    label: S.agents.recipe },
  { key: 'deepdive',  label: S.agents.deepDive },
] as const;

const DEFAULT_FORM: AgentFormData = {
  name: '', display_name: '', display_name_ko: '',
  personality: '', quote: '', color: '#6b7280',
  domain: '', domain_display: '', domain_display_ko: '',
  keywords: [], weighted_keywords: [], recipe_parameters: [],
  model: 'gemini-pro', enabled: true,
  prompts: { screening: '', visual: '', recipe: '', deepdive: '' },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function agentDisplayName(a: AgentDetail): string {
  return a.display_name_ko || a.display_name || a.name;
}

function emptyForm(): AgentFormData {
  return JSON.parse(JSON.stringify(DEFAULT_FORM));
}

function agentToForm(a: AgentDetail): AgentFormData {
  return {
    name: a.name,
    display_name: a.display_name,
    display_name_ko: a.display_name_ko,
    personality: a.personality,
    quote: a.quote,
    color: a.color,
    domain: a.domain,
    domain_display: a.domain_display,
    domain_display_ko: a.domain_display_ko,
    keywords: [...(a.keywords ?? [])],
    weighted_keywords: [...(a.weighted_keywords ?? [])],
    recipe_parameters: [...(a.recipe_parameters ?? [])],
    model: a.model,
    enabled: a.enabled,
    prompts: {
      screening: a.prompts?.screening ?? '',
      visual:    a.prompts?.visual    ?? '',
      recipe:    a.prompts?.recipe    ?? '',
      deepdive:  a.prompts?.deepdive  ?? '',
    },
  };
}

// ---------------------------------------------------------------------------
// Sub-components (inline, no separate files)
// ---------------------------------------------------------------------------

// Tag input: press Enter to add, click X to remove
interface TagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

function TagInput({ tags, onChange, placeholder }: TagInputProps) {
  const [inputVal, setInputVal] = useState('');

  function addTag(raw: string) {
    const val = raw.trim();
    if (!val || tags.includes(val)) { setInputVal(''); return; }
    onChange([...tags, val]);
    setInputVal('');
  }

  return (
    <div className="flex flex-wrap gap-1.5 min-h-[42px] bg-surface-900 border border-surface-700 rounded-lg px-2 py-1.5 focus-within:border-primary-500 transition-colors">
      {tags.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 bg-surface-700 text-surface-200 text-xs px-2 py-0.5 rounded-full"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(tags.filter((t) => t !== tag))}
            className="text-surface-400 hover:text-surface-100 transition-colors"
          >
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={inputVal}
        onChange={(e) => setInputVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); addTag(inputVal); }
          if (e.key === 'Backspace' && !inputVal && tags.length) {
            onChange(tags.slice(0, -1));
          }
        }}
        onBlur={() => { if (inputVal.trim()) addTag(inputVal); }}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="flex-1 min-w-[120px] bg-transparent outline-none text-sm text-surface-200 placeholder-surface-600 py-0.5"
      />
    </div>
  );
}

// Field wrapper
function Field({
  label, help, children,
}: { label: string; help?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-surface-400 mb-1.5">{label}</label>
      {children}
      {help && <p className="text-2xs text-surface-600 mt-1">{help}</p>}
    </div>
  );
}

// Input className shorthand
const inputCls =
  'w-full bg-surface-900 border border-surface-700 rounded-lg px-3 py-2 text-sm text-surface-200 focus:border-primary-500 focus:outline-none transition-colors placeholder-surface-600';

const textareaCls =
  'w-full bg-surface-900 border border-surface-700 rounded-lg px-3 py-2 text-sm text-surface-200 focus:border-primary-500 focus:outline-none transition-colors placeholder-surface-600 font-mono resize-none';

// ---------------------------------------------------------------------------
// Step Indicator
// ---------------------------------------------------------------------------

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-0 mb-8">
      {WIZARD_STEPS.map((step, i) => (
        <div key={step.n} className="flex items-center flex-1">
          <div className="flex flex-col items-center gap-1 flex-1">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold transition-colors ${
                step.n < current
                  ? 'bg-primary-500 text-white'
                  : step.n === current
                  ? 'bg-primary-500/20 border-2 border-primary-500 text-primary-400'
                  : 'bg-surface-800 border border-surface-700 text-surface-500'
              }`}
            >
              {step.n < current ? <Check className="w-4 h-4" /> : step.n}
            </div>
            <span className={`text-2xs whitespace-nowrap ${step.n === current ? 'text-primary-400' : 'text-surface-600'}`}>
              {step.label}
            </span>
          </div>
          {i < total - 1 && (
            <div className={`h-px flex-1 mx-1 mb-5 ${step.n < current ? 'bg-primary-500' : 'bg-surface-700'}`} />
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Color Picker
// ---------------------------------------------------------------------------

function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {PRESET_COLORS.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={`w-7 h-7 rounded-full transition-transform hover:scale-110 ${
            value === c ? 'ring-2 ring-offset-2 ring-offset-surface-900 ring-white scale-110' : ''
          }`}
          style={{ backgroundColor: c }}
          title={c}
        />
      ))}
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-7 h-7 rounded-full border border-surface-600 cursor-pointer bg-transparent"
        title="Custom color"
      />
      <span className="text-xs text-surface-500 font-mono">{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard Steps Content
// ---------------------------------------------------------------------------

function WizardStep1({ form, set }: { form: AgentFormData; set: (k: keyof AgentFormData, v: unknown) => void }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <Field label={S.agents.name} help={S.agents.nameHelp}>
          <input
            className={inputCls}
            value={form.name}
            onChange={(e) => set('name', e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ''))}
            placeholder="my_agent"
          />
        </Field>
        <Field label={S.agents.displayName}>
          <input
            className={inputCls}
            value={form.display_name}
            onChange={(e) => set('display_name', e.target.value)}
            placeholder="My Agent"
          />
        </Field>
      </div>
      <Field label={S.agents.displayNameKo}>
        <input
          className={inputCls}
          value={form.display_name_ko}
          onChange={(e) => set('display_name_ko', e.target.value)}
          placeholder="나의 에이전트"
        />
      </Field>
      <Field label={S.agents.personality} help={S.agents.personalityHelp}>
        <input
          className={inputCls}
          value={form.personality}
          onChange={(e) => set('personality', e.target.value)}
          placeholder="직설적이고 효율적인 분석가"
        />
      </Field>
      <Field label={S.agents.quote} help={S.agents.quoteHelp}>
        <input
          className={inputCls}
          value={form.quote}
          onChange={(e) => set('quote', e.target.value)}
          placeholder="분석 준비 완료."
        />
      </Field>
      <Field label={S.agents.color}>
        <ColorPicker value={form.color} onChange={(c) => set('color', c)} />
      </Field>
    </div>
  );
}

function WizardStep2({ form, set }: { form: AgentFormData; set: (k: keyof AgentFormData, v: unknown) => void }) {
  return (
    <div className="space-y-4">
      <Field label={S.agents.domain}>
        <input
          className={inputCls}
          value={form.domain}
          onChange={(e) => set('domain', e.target.value.toLowerCase())}
          placeholder="optics"
        />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label={S.agents.domainDisplay}>
          <input
            className={inputCls}
            value={form.domain_display}
            onChange={(e) => set('domain_display', e.target.value)}
            placeholder="Optics"
          />
        </Field>
        <Field label={S.agents.domainDisplayKo}>
          <input
            className={inputCls}
            value={form.domain_display_ko}
            onChange={(e) => set('domain_display_ko', e.target.value)}
            placeholder="광학"
          />
        </Field>
      </div>
      <Field label={S.agents.keywords} help={S.agents.keywordsHelp}>
        <TagInput
          tags={form.keywords}
          onChange={(v) => set('keywords', v)}
          placeholder="laser, photon, ..."
        />
      </Field>
      <Field label={S.agents.weightedKeywords} help={S.agents.weightedKeywordsHelp}>
        <TagInput
          tags={form.weighted_keywords}
          onChange={(v) => set('weighted_keywords', v)}
          placeholder="optical fiber, ..."
        />
      </Field>
    </div>
  );
}

function WizardStep3({ form, set }: { form: AgentFormData; set: (k: keyof AgentFormData, v: unknown) => void }) {
  return (
    <div className="space-y-4">
      <Field label={S.agents.recipeParameters} help={S.agents.recipeParametersHelp}>
        <TagInput
          tags={form.recipe_parameters}
          onChange={(v) => set('recipe_parameters', v)}
          placeholder="wavelength, power, ..."
        />
      </Field>
      <Field label={S.agents.model}>
        <select
          className={inputCls}
          value={form.model}
          onChange={(e) => set('model', e.target.value)}
        >
          <option value="gemini-pro">Gemini Pro</option>
          <option value="gemini-flash">Gemini Flash</option>
        </select>
      </Field>
    </div>
  );
}

function WizardStep4({ form, set }: { form: AgentFormData; set: (k: keyof AgentFormData, v: unknown) => void }) {
  const [activeTab, setActiveTab] = useState<typeof PROMPT_TABS[number]['key']>('screening');

  return (
    <div className="space-y-3">
      {/* Tabs */}
      <div className="flex gap-1 bg-surface-900 rounded-lg p-1 border border-surface-700">
        {PROMPT_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 py-1.5 text-xs rounded-md transition-colors font-medium ${
              activeTab === tab.key
                ? 'bg-primary-500/20 text-primary-400'
                : 'text-surface-400 hover:text-surface-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <textarea
        className={`${textareaCls} min-h-[220px]`}
        value={form.prompts[activeTab]}
        onChange={(e) =>
          set('prompts', { ...form.prompts, [activeTab]: e.target.value })
        }
        placeholder={`${activeTab} prompt...`}
      />
    </div>
  );
}

function WizardStep5({ form }: { form: AgentFormData }) {
  const displayName = form.display_name_ko || form.display_name || form.name;

  return (
    <div className="space-y-6">
      {/* Card preview */}
      <div>
        <p className="text-xs text-surface-500 mb-3">{S.agents.preview}</p>
        <div className="bg-surface-800 border border-surface-700/50 rounded-xl p-5 max-w-sm">
          <div className="flex items-center gap-3 mb-3">
            <AgentAvatar name={displayName} color={form.color} size="lg" />
            <div>
              <p className="font-semibold text-surface-100">{displayName || '—'}</p>
              <p className="text-xs text-surface-500">{form.domain_display_ko || form.domain_display || form.domain || '—'}</p>
            </div>
          </div>
          {form.quote && (
            <p className="text-sm text-surface-400 italic mb-3">"{form.quote}"</p>
          )}
          <div className="flex flex-wrap gap-1.5">
            {form.keywords.slice(0, 5).map((kw) => (
              <span key={kw} className="text-2xs bg-surface-700 text-surface-300 px-2 py-0.5 rounded-full">
                {kw}
              </span>
            ))}
            {form.keywords.length > 5 && (
              <span className="text-2xs text-surface-500">+{form.keywords.length - 5}</span>
            )}
          </div>
        </div>
      </div>

      {/* Raw JSON preview */}
      <div>
        <p className="text-xs text-surface-500 mb-2">{S.agents.rawMarkdown}</p>
        <pre className="bg-surface-900 border border-surface-700 rounded-lg p-4 text-xs text-surface-400 font-mono overflow-auto max-h-[200px]">
          {JSON.stringify(
            {
              name: form.name,
              display_name: form.display_name,
              display_name_ko: form.display_name_ko,
              personality: form.personality,
              domain: form.domain,
              color: form.color,
              model: form.model,
              keywords: form.keywords,
            },
            null,
            2
          )}
        </pre>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function Agents() {
  const [mode, setMode] = useState<PageMode>('list');
  const [agents, setAgents] = useState<AgentDetail[]>([]);
  const [editingAgent, setEditingAgent] = useState<AgentDetail | null>(null);
  const [loading, setLoading] = useState(true);

  // Create wizard state
  const [wizardStep, setWizardStep] = useState(1);
  const [formData, setFormData] = useState<AgentFormData>(emptyForm());

  // Edit state
  const [editRawMode, setEditRawMode] = useState(false);
  const [editRawMd, setEditRawMd] = useState('');
  const [editPromptTab, setEditPromptTab] = useState<typeof PROMPT_TABS[number]['key']>('screening');

  // Toast / error
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Confirm delete dialog
  const [deleteTarget, setDeleteTarget] = useState<AgentDetail | null>(null);

  // Import file ref
  const importInputRef = useRef<HTMLInputElement>(null);

  // Submitting
  const [submitting, setSubmitting] = useState(false);

  // -------------------------------------------------------------------------
  // Toast helpers
  // -------------------------------------------------------------------------

  function showToast(message: string, type: 'success' | 'error' = 'success') {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ message, type });
    toastTimerRef.current = setTimeout(() => setToast(null), 3500);
  }

  // -------------------------------------------------------------------------
  // Load agents
  // -------------------------------------------------------------------------

  const loadAgents = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getAgents();
      setAgents(data);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load agents', 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  // -------------------------------------------------------------------------
  // Form field setter
  // -------------------------------------------------------------------------

  function setField(key: keyof AgentFormData, value: unknown) {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }

  // -------------------------------------------------------------------------
  // Wizard navigation
  // -------------------------------------------------------------------------

  function wizardNext() {
    if (wizardStep === 1 && !formData.name.trim()) {
      showToast(S.agents.nameHelp, 'error'); return;
    }
    if (wizardStep === 2 && !formData.domain.trim()) {
      showToast(S.agents.domain + ' 필드가 필요합니다', 'error'); return;
    }
    setWizardStep((s) => Math.min(s + 1, 5));
  }

  function wizardBack() {
    setWizardStep((s) => Math.max(s - 1, 1));
  }

  // -------------------------------------------------------------------------
  // Action: Create
  // -------------------------------------------------------------------------

  async function handleCreate() {
    if (!formData.name.trim()) { showToast(S.agents.nameHelp, 'error'); return; }
    setSubmitting(true);
    try {
      await createAgent({
        name: formData.name,
        display_name: formData.display_name,
        display_name_ko: formData.display_name_ko,
        personality: formData.personality,
        quote: formData.quote,
        color: formData.color,
        domain: formData.domain,
        domain_display: formData.domain_display,
        domain_display_ko: formData.domain_display_ko,
        keywords: formData.keywords,
        weighted_keywords: formData.weighted_keywords,
        recipe_parameters: formData.recipe_parameters,
        model: formData.model,
        enabled: formData.enabled,
        prompts: formData.prompts as Record<string, string>,
      });
      showToast(S.agents.agentCreated);
      await loadAgents();
      setMode('list');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Create failed', 'error');
    } finally {
      setSubmitting(false);
    }
  }

  // -------------------------------------------------------------------------
  // Action: Update
  // -------------------------------------------------------------------------

  async function handleUpdate() {
    if (!editingAgent) return;
    setSubmitting(true);
    try {
      if (editRawMode) {
        await updateAgent(editingAgent.name, { raw_md: editRawMd });
      } else {
        await updateAgent(editingAgent.name, {
          display_name: formData.display_name,
          display_name_ko: formData.display_name_ko,
          personality: formData.personality,
          quote: formData.quote,
          color: formData.color,
          domain: formData.domain,
          domain_display: formData.domain_display,
          domain_display_ko: formData.domain_display_ko,
          keywords: formData.keywords,
          weighted_keywords: formData.weighted_keywords,
          recipe_parameters: formData.recipe_parameters,
          model: formData.model,
          enabled: formData.enabled,
          prompts: formData.prompts as Record<string, string>,
        });
      }
      showToast(S.agents.agentUpdated);
      await loadAgents();
      setMode('list');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Update failed', 'error');
    } finally {
      setSubmitting(false);
    }
  }

  // -------------------------------------------------------------------------
  // Action: Delete
  // -------------------------------------------------------------------------

  async function handleDelete(agent: AgentDetail) {
    if (agent.builtin) { showToast(S.agents.cannotDeleteBuiltin, 'error'); return; }
    setDeleteTarget(agent);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await deleteAgent(deleteTarget.name);
      showToast(S.agents.agentDeleted);
      await loadAgents();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Delete failed', 'error');
    } finally {
      setDeleteTarget(null);
    }
  }

  // -------------------------------------------------------------------------
  // Action: Duplicate
  // -------------------------------------------------------------------------

  async function handleDuplicate(agent: AgentDetail) {
    try {
      await duplicateAgent(agent.name);
      showToast(S.agents.duplicateSuccess);
      await loadAgents();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Duplicate failed', 'error');
    }
  }

  // -------------------------------------------------------------------------
  // Action: Toggle
  // -------------------------------------------------------------------------

  async function handleToggle(agent: AgentDetail) {
    try {
      await toggleAgent(agent.name, !agent.enabled);
      await loadAgents();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Toggle failed', 'error');
    }
  }

  // -------------------------------------------------------------------------
  // Action: Export
  // -------------------------------------------------------------------------

  async function handleExport(agent: AgentDetail) {
    try {
      const md = await exportAgent(agent.name);
      const blob = new Blob([md], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${agent.name}.md`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast(S.agents.exportSuccess);
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Export failed', 'error');
    }
  }

  // -------------------------------------------------------------------------
  // Action: Import
  // -------------------------------------------------------------------------

  function handleImportClick() {
    importInputRef.current?.click();
  }

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.endsWith('.md')) {
      showToast(S.agents.invalidFile, 'error');
      return;
    }
    try {
      await importAgent(file);
      showToast(S.agents.importSuccess);
      await loadAgents();
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Import failed', 'error');
    } finally {
      if (importInputRef.current) importInputRef.current.value = '';
    }
  }

  // -------------------------------------------------------------------------
  // Enter Edit mode
  // -------------------------------------------------------------------------

  async function enterEdit(agent: AgentDetail) {
    try {
      const full = await getAgent(agent.name);
      setEditingAgent(full);
      setFormData(agentToForm(full));
      setEditRawMd(full.raw_md ?? '');
      setEditRawMode(false);
      setEditPromptTab('screening');
      setMode('edit');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to load agent', 'error');
    }
  }

  // -------------------------------------------------------------------------
  // Enter Create mode
  // -------------------------------------------------------------------------

  function enterCreate() {
    setFormData(emptyForm());
    setWizardStep(1);
    setMode('create');
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-6 max-w-5xl mx-auto">

        {/* Toast */}
        {toast && (
          <div
            className={`fixed top-4 right-4 z-50 flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg text-sm border transition-all ${
              toast.type === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                : 'bg-red-500/10 border-red-500/30 text-red-300'
            }`}
          >
            {toast.type === 'success' ? (
              <Check className="w-4 h-4 shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 shrink-0" />
            )}
            {toast.message}
            <button
              type="button"
              onClick={() => setToast(null)}
              className="ml-2 opacity-60 hover:opacity-100"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Delete confirmation dialog */}
        {deleteTarget && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="bg-surface-800 border border-surface-700 rounded-xl p-6 w-full max-w-sm shadow-2xl">
              <div className="flex items-center gap-3 mb-4">
                <div className="w-10 h-10 rounded-full bg-red-500/10 flex items-center justify-center">
                  <Trash2 className="w-5 h-5 text-red-400" />
                </div>
                <div>
                  <p className="font-semibold text-surface-100">{S.agents.confirmDelete}</p>
                  <p className="text-sm text-surface-400">{agentDisplayName(deleteTarget)}</p>
                </div>
              </div>
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => setDeleteTarget(null)}
                  className="bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-lg px-4 py-2 text-sm transition-colors"
                >
                  {S.agents.cancel}
                </button>
                <button
                  type="button"
                  onClick={confirmDelete}
                  className="bg-red-500 hover:bg-red-600 text-white rounded-lg px-4 py-2 text-sm transition-colors"
                >
                  {S.agents.delete_}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Hidden import file input */}
        <input
          ref={importInputRef}
          type="file"
          accept=".md"
          className="hidden"
          onChange={handleImportFile}
        />

        {/* ================================================================= */}
        {/* MODE: LIST */}
        {/* ================================================================= */}
        {mode === 'list' && (
          <>
            {/* Header */}
            <div className="flex items-start justify-between mb-6">
              <div>
                <h1 className="text-xl font-bold text-surface-100">{S.agents.title}</h1>
                <p className="text-sm text-surface-500 mt-1">{S.agents.description}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleImportClick}
                  className="flex items-center gap-1.5 bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-lg px-3 py-2 text-sm transition-colors"
                >
                  <Upload className="w-4 h-4" />
                  {S.agents.import_}
                </button>
                <button
                  type="button"
                  onClick={enterCreate}
                  className="flex items-center gap-1.5 bg-primary-500 hover:bg-primary-600 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  {S.agents.createNew}
                </button>
              </div>
            </div>

            {/* Agent grid */}
            {loading ? (
              <div className="flex items-center justify-center py-24 text-surface-500 text-sm">
                불러오는 중...
              </div>
            ) : agents.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-24 gap-3">
                <p className="text-surface-400 font-medium">{S.agents.noAgents}</p>
                <p className="text-surface-600 text-sm">{S.agents.noAgentsDesc}</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {agents.map((agent) => {
                  const name = agentDisplayName(agent);
                  return (
                    <div
                      key={agent.name}
                      className={`bg-surface-800 border border-surface-700/50 rounded-xl p-5 flex flex-col gap-3 transition-opacity ${
                        !agent.enabled ? 'opacity-50' : ''
                      }`}
                    >
                      {/* Top row */}
                      <div className="flex items-center gap-3">
                        <AgentAvatar name={name} color={agent.color} size="md" />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-semibold text-surface-100 truncate">
                              {name}
                            </span>
                            {agent.builtin ? (
                              <span className="text-2xs bg-surface-700 text-surface-400 px-1.5 py-0.5 rounded">
                                {S.agents.builtin}
                              </span>
                            ) : (
                              <span className="text-2xs bg-primary-500/10 text-primary-400 border border-primary-500/20 px-1.5 py-0.5 rounded">
                                {S.agents.custom}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-surface-500 truncate">{agent.name}</p>
                        </div>
                      </div>

                      {/* Quote */}
                      {agent.quote && (
                        <p className="text-sm text-surface-400 italic leading-snug line-clamp-2">
                          "{agent.quote}"
                        </p>
                      )}

                      {/* Domain + keyword count */}
                      <div className="flex items-center gap-2 flex-wrap">
                        {(agent.domain_display_ko || agent.domain_display) && (
                          <span className="text-2xs bg-surface-700 text-surface-300 px-2 py-0.5 rounded-full">
                            {agent.domain_display_ko || agent.domain_display}
                          </span>
                        )}
                        {agent.keywords?.length > 0 && (
                          <span className="text-2xs text-surface-500">
                            키워드 {agent.keywords.length}개
                          </span>
                        )}
                        <span className={`text-2xs ml-auto ${agent.enabled ? 'text-emerald-400' : 'text-surface-500'}`}>
                          {agent.enabled ? S.agents.enabled : S.agents.disabled}
                        </span>
                      </div>

                      {/* Action buttons */}
                      <div className="flex items-center gap-1 border-t border-surface-700/50 pt-3">
                        <button
                          type="button"
                          onClick={() => enterEdit(agent)}
                          className="flex items-center gap-1 bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-lg px-2.5 py-1.5 text-xs transition-colors"
                          title={S.agents.edit}
                        >
                          <Edit3 className="w-3.5 h-3.5" />
                          {S.agents.edit}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDuplicate(agent)}
                          className="flex items-center gap-1 bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-lg px-2.5 py-1.5 text-xs transition-colors"
                          title={S.agents.duplicate}
                        >
                          <Copy className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleExport(agent)}
                          className="flex items-center gap-1 bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-lg px-2.5 py-1.5 text-xs transition-colors"
                          title={S.agents.export_}
                        >
                          <Download className="w-3.5 h-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={() => handleToggle(agent)}
                          className={`flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs transition-colors ${
                            agent.enabled
                              ? 'bg-surface-700 hover:bg-surface-600 text-surface-200'
                              : 'bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400'
                          }`}
                          title={agent.enabled ? S.agents.disabled : S.agents.enabled}
                        >
                          {agent.enabled ? (
                            <PowerOff className="w-3.5 h-3.5" />
                          ) : (
                            <Power className="w-3.5 h-3.5" />
                          )}
                        </button>
                        {!agent.builtin && (
                          <button
                            type="button"
                            onClick={() => handleDelete(agent)}
                            className="flex items-center gap-1 bg-red-500/10 text-red-400 hover:bg-red-500/20 rounded-lg px-2.5 py-1.5 text-xs transition-colors ml-auto"
                            title={S.agents.delete_}
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {/* ================================================================= */}
        {/* MODE: CREATE (Wizard) */}
        {/* ================================================================= */}
        {mode === 'create' && (
          <>
            {/* Header */}
            <div className="flex items-center gap-3 mb-6">
              <button
                type="button"
                onClick={() => setMode('list')}
                className="flex items-center gap-1.5 text-surface-400 hover:text-surface-200 text-sm transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
                {S.agents.back}
              </button>
              <h1 className="text-xl font-bold text-surface-100">{S.agents.createNew}</h1>
            </div>

            <div className="bg-surface-800 border border-surface-700/50 rounded-xl p-6">
              <StepIndicator current={wizardStep} total={5} />

              {/* Step content */}
              {wizardStep === 1 && <WizardStep1 form={formData} set={setField} />}
              {wizardStep === 2 && <WizardStep2 form={formData} set={setField} />}
              {wizardStep === 3 && <WizardStep3 form={formData} set={setField} />}
              {wizardStep === 4 && <WizardStep4 form={formData} set={setField} />}
              {wizardStep === 5 && <WizardStep5 form={formData} />}

              {/* Navigation */}
              <div className="flex items-center justify-between mt-8 pt-5 border-t border-surface-700/50">
                <button
                  type="button"
                  onClick={wizardStep === 1 ? () => setMode('list') : wizardBack}
                  className="flex items-center gap-1.5 bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-lg px-4 py-2 text-sm transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                  {wizardStep === 1 ? S.agents.cancel : S.agents.previous}
                </button>

                {wizardStep < 5 ? (
                  <button
                    type="button"
                    onClick={wizardNext}
                    className="flex items-center gap-1.5 bg-primary-500 hover:bg-primary-600 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    {S.agents.next}
                    <ChevronRight className="w-4 h-4" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleCreate}
                    disabled={submitting}
                    className="flex items-center gap-1.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-60 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                  >
                    <Check className="w-4 h-4" />
                    {submitting ? '...' : S.agents.create}
                  </button>
                )}
              </div>
            </div>
          </>
        )}

        {/* ================================================================= */}
        {/* MODE: EDIT */}
        {/* ================================================================= */}
        {mode === 'edit' && editingAgent && (
          <>
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setMode('list')}
                  className="flex items-center gap-1.5 text-surface-400 hover:text-surface-200 text-sm transition-colors"
                >
                  <ChevronLeft className="w-4 h-4" />
                  {S.agents.back}
                </button>
                <div className="flex items-center gap-2">
                  <AgentAvatar name={agentDisplayName(editingAgent)} color={editingAgent.color} size="sm" />
                  <h1 className="text-xl font-bold text-surface-100">
                    {agentDisplayName(editingAgent)}
                  </h1>
                  {editingAgent.builtin && (
                    <span className="text-2xs bg-surface-700 text-surface-400 px-1.5 py-0.5 rounded">
                      {S.agents.builtin}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2">
                {/* Mode toggle */}
                <div className="flex bg-surface-900 border border-surface-700 rounded-lg p-0.5">
                  <button
                    type="button"
                    onClick={() => setEditRawMode(false)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md transition-colors ${
                      !editRawMode ? 'bg-primary-500/20 text-primary-400' : 'text-surface-400 hover:text-surface-200'
                    }`}
                  >
                    <Eye className="w-3.5 h-3.5" />
                    {S.agents.formMode}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditRawMode(true)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md transition-colors ${
                      editRawMode ? 'bg-primary-500/20 text-primary-400' : 'text-surface-400 hover:text-surface-200'
                    }`}
                  >
                    <Code className="w-3.5 h-3.5" />
                    {S.agents.rawMarkdown}
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => setMode('list')}
                  className="bg-surface-700 hover:bg-surface-600 text-surface-200 rounded-lg px-3 py-2 text-sm transition-colors"
                >
                  {S.agents.cancel}
                </button>
                <button
                  type="button"
                  onClick={handleUpdate}
                  disabled={submitting}
                  className="flex items-center gap-1.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-60 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors"
                >
                  <Check className="w-4 h-4" />
                  {submitting ? '...' : S.agents.save}
                </button>
              </div>
            </div>

            {/* Builtin notice */}
            {editingAgent.builtin && (
              <div className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 text-amber-300 text-sm rounded-lg px-4 py-3 mb-4">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                기본 에이전트를 수정하면 사용자 정의 버전이 생성됩니다.
              </div>
            )}

            <div className="bg-surface-800 border border-surface-700/50 rounded-xl p-6">
              {editRawMode ? (
                /* Raw markdown edit */
                <div className="space-y-2">
                  <label className="text-xs text-surface-400">{S.agents.rawMarkdown}</label>
                  <textarea
                    className={`${textareaCls} min-h-[500px]`}
                    value={editRawMd}
                    onChange={(e) => setEditRawMd(e.target.value)}
                    placeholder="# Agent markdown content..."
                  />
                </div>
              ) : (
                /* Form edit (all fields on one scrollable page) */
                <div className="space-y-6">
                  {/* Identity section */}
                  <div>
                    <h2 className="text-sm font-semibold text-surface-200 mb-4">{S.agents.stepIdentity}</h2>
                    <div className="space-y-4">
                      <div className="grid grid-cols-2 gap-4">
                        <Field label={S.agents.displayName}>
                          <input className={inputCls} value={formData.display_name} onChange={(e) => setField('display_name', e.target.value)} />
                        </Field>
                        <Field label={S.agents.displayNameKo}>
                          <input className={inputCls} value={formData.display_name_ko} onChange={(e) => setField('display_name_ko', e.target.value)} />
                        </Field>
                      </div>
                      <Field label={S.agents.personality} help={S.agents.personalityHelp}>
                        <input className={inputCls} value={formData.personality} onChange={(e) => setField('personality', e.target.value)} />
                      </Field>
                      <Field label={S.agents.quote} help={S.agents.quoteHelp}>
                        <input className={inputCls} value={formData.quote} onChange={(e) => setField('quote', e.target.value)} />
                      </Field>
                      <Field label={S.agents.color}>
                        <ColorPicker value={formData.color} onChange={(c) => setField('color', c)} />
                      </Field>
                    </div>
                  </div>

                  <div className="border-t border-surface-700/50" />

                  {/* Domain section */}
                  <div>
                    <h2 className="text-sm font-semibold text-surface-200 mb-4">{S.agents.stepDomain}</h2>
                    <div className="space-y-4">
                      <Field label={S.agents.domain}>
                        <input className={inputCls} value={formData.domain} onChange={(e) => setField('domain', e.target.value)} />
                      </Field>
                      <div className="grid grid-cols-2 gap-4">
                        <Field label={S.agents.domainDisplay}>
                          <input className={inputCls} value={formData.domain_display} onChange={(e) => setField('domain_display', e.target.value)} />
                        </Field>
                        <Field label={S.agents.domainDisplayKo}>
                          <input className={inputCls} value={formData.domain_display_ko} onChange={(e) => setField('domain_display_ko', e.target.value)} />
                        </Field>
                      </div>
                      <Field label={S.agents.keywords} help={S.agents.keywordsHelp}>
                        <TagInput tags={formData.keywords} onChange={(v) => setField('keywords', v)} />
                      </Field>
                      <Field label={S.agents.weightedKeywords} help={S.agents.weightedKeywordsHelp}>
                        <TagInput tags={formData.weighted_keywords} onChange={(v) => setField('weighted_keywords', v)} />
                      </Field>
                    </div>
                  </div>

                  <div className="border-t border-surface-700/50" />

                  {/* Parameters section */}
                  <div>
                    <h2 className="text-sm font-semibold text-surface-200 mb-4">{S.agents.stepParameters}</h2>
                    <div className="space-y-4">
                      <Field label={S.agents.recipeParameters} help={S.agents.recipeParametersHelp}>
                        <TagInput tags={formData.recipe_parameters} onChange={(v) => setField('recipe_parameters', v)} />
                      </Field>
                      <Field label={S.agents.model}>
                        <select className={inputCls} value={formData.model} onChange={(e) => setField('model', e.target.value)}>
                          <option value="gemini-pro">Gemini Pro</option>
                          <option value="gemini-flash">Gemini Flash</option>
                        </select>
                      </Field>
                    </div>
                  </div>

                  <div className="border-t border-surface-700/50" />

                  {/* Prompts section */}
                  <div>
                    <h2 className="text-sm font-semibold text-surface-200 mb-4">{S.agents.stepPrompts}</h2>
                    <div className="flex gap-1 bg-surface-900 rounded-lg p-1 border border-surface-700 mb-3">
                      {PROMPT_TABS.map((tab) => (
                        <button
                          key={tab.key}
                          type="button"
                          onClick={() => setEditPromptTab(tab.key)}
                          className={`flex-1 py-1.5 text-xs rounded-md transition-colors font-medium ${
                            editPromptTab === tab.key
                              ? 'bg-primary-500/20 text-primary-400'
                              : 'text-surface-400 hover:text-surface-200'
                          }`}
                        >
                          {tab.label}
                        </button>
                      ))}
                    </div>
                    <textarea
                      className={`${textareaCls} min-h-[220px]`}
                      value={formData.prompts[editPromptTab]}
                      onChange={(e) =>
                        setField('prompts', { ...formData.prompts, [editPromptTab]: e.target.value })
                      }
                      placeholder={`${editPromptTab} prompt...`}
                    />
                  </div>
                </div>
              )}
            </div>
          </>
        )}

      </div>
    </div>
  );
}
