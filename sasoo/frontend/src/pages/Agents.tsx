import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { S } from '@/lib/strings';
import { fetchAllAgents } from '@/lib/agents';
import {
  getAgents, getAgent, createAgent, updateAgent, deleteAgent,
  duplicateAgent, exportAgent, importAgent,
  generateAgent,
  type AgentDetail,
} from '@/lib/api';
import AgentAvatar from '@/components/AgentAvatar';
import Modal from '@/components/ui/Modal';
import Toggle from '@/components/ui/Toggle';
import {
  AlertTriangle,
  Check,
  ChevronLeft,
  Code,
  Copy,
  Download,
  Edit3,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
  X,
} from 'lucide-react';

type PageMode = 'list' | 'author';
type AuthorMode = 'create' | 'edit';
type AuthorStep = 'basic' | 'advanced';
type CreateStartMode = 'direct' | 'ai';
type ExpertView = 'prompts' | 'raw';
type PromptKey = 'screening' | 'visual' | 'recipe' | 'deepdive';

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
  prompts: Record<PromptKey, string>;
}

interface ToastState {
  message: string;
  type: 'success' | 'error';
}

const PRESET_COLORS = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#06b6d4', '#6366f1', '#a855f7', '#ec4899',
];

const PROMPT_TABS: Array<{ key: PromptKey; label: string }> = [
  { key: 'screening', label: S.agents.screening },
  { key: 'visual', label: S.agents.visual },
  { key: 'recipe', label: S.agents.recipe },
  { key: 'deepdive', label: S.agents.deepDive },
];

const DEFAULT_FORM: AgentFormData = {
  name: '',
  display_name: '',
  display_name_ko: '',
  personality: '',
  quote: '',
  color: '#6b7280',
  domain: '',
  domain_display: '',
  domain_display_ko: '',
  keywords: [],
  weighted_keywords: [],
  recipe_parameters: [],
  model: 'gemini-pro',
  enabled: true,
  prompts: {
    screening: '',
    visual: '',
    recipe: '',
    deepdive: '',
  },
};

const inputCls =
  'w-full bg-surface-900 border border-surface-700 rounded-lg px-3 py-2 text-sm text-surface-200 focus:border-primary-500 focus:outline-none transition-colors placeholder-surface-600';

const textareaCls =
  'w-full bg-surface-900 border border-surface-700 rounded-lg px-3 py-2 text-sm text-surface-200 focus:border-primary-500 focus:outline-none transition-colors placeholder-surface-600 resize-none';

function emptyForm(): AgentFormData {
  return JSON.parse(JSON.stringify(DEFAULT_FORM));
}

function agentDisplayName(agent: Pick<AgentDetail, 'display_name_ko' | 'display_name' | 'name'>): string {
  return agent.display_name_ko || agent.display_name || agent.name;
}

function agentToForm(agent: AgentDetail): AgentFormData {
  return {
    name: agent.name,
    display_name: agent.display_name,
    display_name_ko: agent.display_name_ko,
    personality: agent.personality,
    quote: agent.quote,
    color: agent.color,
    domain: agent.domain,
    domain_display: agent.domain_display,
    domain_display_ko: agent.domain_display_ko,
    keywords: [...(agent.keywords ?? [])],
    weighted_keywords: [...(agent.weighted_keywords ?? [])],
    recipe_parameters: [...(agent.recipe_parameters ?? [])],
    model: agent.model,
    enabled: agent.enabled,
    prompts: {
      screening: agent.prompts?.screening ?? '',
      visual: agent.prompts?.visual ?? '',
      recipe: agent.prompts?.recipe ?? '',
      deepdive: agent.prompts?.deepdive ?? '',
    },
  };
}

function sanitizeAgentName(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_]/g, '');
}

function yamlScalar(value: string | boolean): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return JSON.stringify(value ?? '');
}

function yamlList(name: string, values: string[]): string[] {
  if (values.length === 0) return [`${name}: []`];
  return [`${name}:`, ...values.map((value) => `  - ${yamlScalar(value)}`)];
}

function serializeAgentMarkdown(form: AgentFormData): string {
  const lines: string[] = [
    '---',
    `name: ${yamlScalar(form.name)}`,
    `display_name: ${yamlScalar(form.display_name)}`,
    `display_name_ko: ${yamlScalar(form.display_name_ko)}`,
    `personality: ${yamlScalar(form.personality)}`,
    `quote: ${yamlScalar(form.quote)}`,
    `color: ${yamlScalar(form.color)}`,
    `domain: ${yamlScalar(form.domain)}`,
    `domain_display: ${yamlScalar(form.domain_display)}`,
    `domain_display_ko: ${yamlScalar(form.domain_display_ko)}`,
    ...yamlList('keywords', form.keywords),
    ...yamlList('weighted_keywords', form.weighted_keywords),
    ...yamlList('recipe_parameters', form.recipe_parameters),
    `model: ${yamlScalar(form.model)}`,
    `enabled: ${yamlScalar(form.enabled)}`,
    '---',
    '',
  ];

  const sections = [
    ['# Screening', form.prompts.screening],
    ['# Visual', form.prompts.visual],
    ['# Recipe', form.prompts.recipe],
    ['# Deep Dive', form.prompts.deepdive],
  ].filter(([, value]) => value.trim().length > 0);

  if (sections.length === 0) return `${lines.join('\n')}\n`;

  return `${lines.join('\n')}${sections.map(([heading, value]) => `${heading}\n\n${value.trim()}`).join('\n\n')}\n`;
}

function buildStructuredPayload(form: AgentFormData) {
  return {
    name: form.name,
    display_name: form.display_name,
    display_name_ko: form.display_name_ko,
    personality: form.personality,
    quote: form.quote,
    color: form.color,
    domain: form.domain,
    domain_display: form.domain_display,
    domain_display_ko: form.domain_display_ko,
    keywords: form.keywords,
    weighted_keywords: form.weighted_keywords,
    recipe_parameters: form.recipe_parameters,
    model: form.model,
    enabled: form.enabled,
    prompts: form.prompts,
  };
}

interface TagInputProps {
  tags: string[];
  onChange: (tags: string[]) => void;
  placeholder?: string;
}

function TagInput({ tags, onChange, placeholder }: TagInputProps) {
  const [inputVal, setInputVal] = useState('');

  function addTag(raw: string) {
    const value = raw.trim();
    if (!value || tags.includes(value)) {
      setInputVal('');
      return;
    }
    onChange([...tags, value]);
    setInputVal('');
  }

  return (
    <div className="flex min-h-[42px] flex-wrap gap-1.5 rounded-lg border border-surface-700 bg-surface-900 px-2 py-1.5 transition-colors focus-within:border-primary-500">
      {tags.map((tag) => (
        <span
          key={tag}
          className="flex items-center gap-1 rounded-full bg-surface-700 px-2 py-0.5 text-xs text-surface-200"
        >
          {tag}
          <button
            type="button"
            onClick={() => onChange(tags.filter((entry) => entry !== tag))}
            className="text-surface-400 transition-colors hover:text-surface-100"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={inputVal}
        onChange={(e) => setInputVal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            addTag(inputVal);
          }
          if (e.key === 'Backspace' && !inputVal && tags.length > 0) {
            onChange(tags.slice(0, -1));
          }
        }}
        onBlur={() => {
          if (inputVal.trim()) addTag(inputVal);
        }}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="min-w-[120px] flex-1 bg-transparent py-0.5 text-sm text-surface-200 outline-none placeholder-surface-600"
      />
    </div>
  );
}

function Field({
  label,
  help,
  children,
}: {
  label: string;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-xs text-surface-400">{label}</label>
      {children}
      {help && <p className="mt-1 text-2xs text-surface-600">{help}</p>}
    </div>
  );
}

function Section({
  title,
  body,
  children,
}: {
  title: string;
  body?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-surface-700/50 bg-surface-800/85 p-5">
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-surface-100">{title}</h2>
        {body && <p className="mt-1 text-xs leading-relaxed text-surface-500">{body}</p>}
      </div>
      {children}
    </section>
  );
}

function ColorPicker({ value, onChange }: { value: string; onChange: (color: string) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {PRESET_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          onClick={() => onChange(color)}
          className={`h-7 w-7 rounded-full transition-transform hover:scale-110 ${
            value === color ? 'scale-110 ring-2 ring-white ring-offset-2 ring-offset-surface-900' : ''
          }`}
          style={{ backgroundColor: color }}
          title={color}
        />
      ))}
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-7 w-7 cursor-pointer rounded-full border border-surface-600 bg-transparent"
        title="Custom color"
      />
      <span className="font-mono text-xs text-surface-500">{value}</span>
    </div>
  );
}

function MetaBadge({
  children,
  tone = 'neutral',
}: {
  children: React.ReactNode;
  tone?: 'neutral' | 'accent' | 'success' | 'warning';
}) {
  const cls = {
    neutral: 'border-surface-700/60 text-surface-400 bg-surface-900/40',
    accent: 'border-primary-500/20 text-primary-300 bg-primary-500/10',
    success: 'border-emerald-500/20 text-emerald-300 bg-emerald-500/10',
    warning: 'border-amber-500/20 text-amber-300 bg-amber-500/10',
  } as const;

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-1 text-2xs ${cls[tone]}`}>
      {children}
    </span>
  );
}

function normalizeAgentError(err: unknown, fallback: string): string {
  if (!(err instanceof Error)) return fallback;
  if (
    err.message.startsWith('Request failed:') ||
    err.message === 'Internal Server Error' ||
    err.message === 'Failed to fetch'
  ) {
    return fallback;
  }
  return err.message;
}

export default function Agents() {
  const [mode, setMode] = useState<PageMode>('list');
  const [authorMode, setAuthorMode] = useState<AuthorMode>('create');
  const [authorStep, setAuthorStep] = useState<AuthorStep>('basic');
  const [createStartMode, setCreateStartMode] = useState<CreateStartMode>('direct');
  const [createChoiceOpen, setCreateChoiceOpen] = useState(false);
  const [agents, setAgents] = useState<AgentDetail[]>([]);
  const [editingAgent, setEditingAgent] = useState<AgentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [authorLoading, setAuthorLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedDraft, setGeneratedDraft] = useState(false);
  const [expertView, setExpertView] = useState<ExpertView>('prompts');
  const [expertPromptTab, setExpertPromptTab] = useState<PromptKey>('screening');
  const [rawDirty, setRawDirty] = useState(false);
  const [editRawMd, setEditRawMd] = useState('');
  const [formData, setFormData] = useState<AgentFormData>(emptyForm());
  const [generateInput, setGenerateInput] = useState({
    domain_description: '',
    personality_hint: '',
    color: '#6b7280',
  });
  const [toast, setToast] = useState<ToastState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AgentDetail | null>(null);

  const importInputRef = useRef<HTMLInputElement>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const rawPreview = useMemo(() => serializeAgentMarkdown(formData), [formData]);
  const previewName = formData.display_name_ko || formData.display_name || formData.name || '새 에이전트';
  const previewDomain = formData.domain_display_ko || formData.domain_display || formData.domain || '도메인 미정';
  const routingSummary = useMemo(() => {
    const keywordCount = formData.keywords.length;
    const weightedCount = formData.weighted_keywords.length;
    if (!formData.domain && keywordCount === 0 && weightedCount === 0) {
      return '아직 맡길 논문 범위가 정해지지 않았습니다. 도메인과 키워드를 먼저 채우면 배정 기준이 분명해집니다.';
    }
    return [
      formData.domain ? `${previewDomain} 분야 논문을 우선 검토합니다.` : '도메인 기준은 아직 비어 있습니다.',
      keywordCount > 0 ? `일반 키워드 ${keywordCount}개로 넓은 분류를 잡습니다.` : '일반 키워드는 아직 없습니다.',
      weightedCount > 0 ? `가중 키워드 ${weightedCount}개가 강한 배정 신호로 작동합니다.` : '가중 키워드는 아직 없습니다.',
    ].join(' ');
  }, [formData.domain, formData.keywords.length, formData.weighted_keywords.length, previewDomain]);

  const outputSummary = useMemo(() => {
    if (formData.recipe_parameters.length === 0) {
      return '아직 강조할 실험 파라미터가 없습니다. 자주 확인해야 할 변수부터 넣으면 결과가 더 실용적입니다.';
    }
    return `${formData.recipe_parameters.slice(0, 4).join(', ')} 중심으로 답변합니다${formData.recipe_parameters.length > 4 ? ` 외 ${formData.recipe_parameters.length - 4}개` : ''}.`;
  }, [formData.recipe_parameters]);

  const tonePreview = useMemo(() => {
    const personality = formData.personality || '차분하고 신뢰감 있는';
    const quote = formData.quote || '핵심부터 빠르게 정리해볼게요.';
    return `${previewName}는 ${personality} 톤으로 답하고, 첫 문장은 "${quote}"에 가깝습니다.`;
  }, [formData.personality, formData.quote, previewName]);

  const authorTitle = authorMode === 'create'
    ? '새 에이전트'
    : agentDisplayName(editingAgent ?? {
      name: formData.name,
      display_name: formData.display_name,
      display_name_ko: formData.display_name_ko,
    });

  const isCreateMode = authorMode === 'create';
  const isEditingBuiltin = Boolean(editingAgent?.builtin);
  const isAdvancedStep = authorStep === 'advanced';
  const saveUsesRaw = rawDirty;
  const builtinCount = agents.filter((agent) => agent.builtin).length;
  const activeCount = agents.filter((agent) => agent.enabled).length;

  function showToast(message: string, type: 'success' | 'error' = 'success') {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ message, type });
    toastTimerRef.current = setTimeout(() => setToast(null), 3500);
  }

  const loadAgents = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getAgents();
      setAgents(data);
      fetchAllAgents().catch(() => {});
    } catch (err) {
      showToast(normalizeAgentError(err, '에이전트 편성 정보를 불러오지 못했습니다.'), 'error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, [loadAgents]);

  useEffect(() => {
    if (!rawDirty) {
      setEditRawMd(rawPreview);
    }
  }, [rawDirty, rawPreview]);

  function setField<K extends keyof AgentFormData>(key: K, value: AgentFormData[K]) {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }

  function resetAuthorState(startMode: CreateStartMode) {
    setMode('author');
    setAuthorMode('create');
    setAuthorStep('basic');
    setCreateStartMode(startMode);
    setEditingAgent(null);
    setFormData(emptyForm());
    setGenerateInput({
      domain_description: '',
      personality_hint: '',
      color: '#6b7280',
    });
    setGeneratedDraft(false);
    setExpertView('prompts');
    setExpertPromptTab('screening');
    setRawDirty(false);
    setEditRawMd('');
  }

  function enterCreate(startMode: CreateStartMode) {
    setCreateChoiceOpen(false);
    resetAuthorState(startMode);
  }

  async function enterEdit(agent: AgentDetail) {
    setAuthorLoading(true);
    try {
      const detail = await getAgent(agent.name);
      setMode('author');
      setAuthorMode('edit');
      setAuthorStep('basic');
      setCreateStartMode('direct');
      setEditingAgent(detail);
      setFormData(agentToForm(detail));
      setGeneratedDraft(false);
      setExpertView('prompts');
      setExpertPromptTab('screening');
      setRawDirty(false);
      setEditRawMd(detail.raw_md || serializeAgentMarkdown(agentToForm(detail)));
    } catch (err) {
      showToast(normalizeAgentError(err, '에이전트 초안을 열지 못했습니다.'), 'error');
    } finally {
      setAuthorLoading(false);
    }
  }

  async function handleGenerateDraft() {
    if (!generateInput.domain_description.trim()) {
      showToast(S.agents.domainDescriptionHelp, 'error');
      return;
    }

    setGenerating(true);
    try {
      const result = await generateAgent({
        domain_description: generateInput.domain_description,
        personality_hint: generateInput.personality_hint || undefined,
        color: generateInput.color || undefined,
      });
      const nextForm = agentToForm(result);
      setFormData(nextForm);
      setGeneratedDraft(true);
      setRawDirty(false);
      setEditRawMd(result.raw_md || serializeAgentMarkdown(nextForm));
      showToast('AI 초안을 불러왔습니다. 맡길 논문 범위와 답변 톤을 먼저 검토하세요.');
    } catch (err) {
      showToast(normalizeAgentError(err, S.agents.generateFailed), 'error');
    } finally {
      setGenerating(false);
    }
  }

  async function handleSave() {
    if (!formData.name.trim()) {
      showToast(S.agents.nameHelp, 'error');
      return;
    }

    setSubmitting(true);
    try {
      const payload = saveUsesRaw
        ? { name: formData.name, raw_md: editRawMd || rawPreview }
        : buildStructuredPayload(formData);

      if (authorMode === 'create') {
        await createAgent(payload);
        showToast(S.agents.agentCreated);
      } else if (editingAgent) {
        await updateAgent(editingAgent.name, payload);
        showToast(S.agents.agentUpdated);
      }

      await loadAgents();
      setMode('list');
      setEditingAgent(null);
      setGeneratedDraft(false);
      setAuthorStep('basic');
      setRawDirty(false);
    } catch (err) {
      showToast(normalizeAgentError(err, '에이전트를 저장하지 못했습니다.'), 'error');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDuplicate(agent: AgentDetail) {
    try {
      await duplicateAgent(agent.name);
      showToast(S.agents.duplicateSuccess);
      await loadAgents();
    } catch (err) {
      showToast(normalizeAgentError(err, '에이전트를 복제하지 못했습니다.'), 'error');
    }
  }

  async function handleExport(agent: AgentDetail) {
    try {
      const md = await exportAgent(agent.name);
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${agent.name}.md`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(S.agents.exportSuccess);
    } catch (err) {
      showToast(normalizeAgentError(err, '에이전트를 내보내지 못했습니다.'), 'error');
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    try {
      await deleteAgent(deleteTarget.name);
      showToast(S.agents.agentDeleted);
      setDeleteTarget(null);
      setMode('list');
      await loadAgents();
    } catch (err) {
      showToast(normalizeAgentError(err, '에이전트를 삭제하지 못했습니다.'), 'error');
    }
  }

  function handleImportClick() {
    importInputRef.current?.click();
  }

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await importAgent(file);
      showToast(S.agents.importSuccess);
      await loadAgents();
    } catch (err) {
      showToast(normalizeAgentError(err, S.agents.invalidFile), 'error');
    } finally {
      e.target.value = '';
    }
  }

  function renderAuthorActions() {
    const target = editingAgent ?? ({
      ...formData,
      builtin: false,
    } as AgentDetail);

    return (
      <div className="rounded-2xl border border-surface-700/50 bg-surface-800/85 p-5">
        <div className="mb-3">
          <h2 className="text-sm font-semibold text-surface-100">보조 작업</h2>
          <p className="mt-1 text-xs leading-relaxed text-surface-500">
            기본 편집과 고급 편집 모두 같은 드래프트를 저장합니다. 복제, 내보내기, 삭제는 여기에서만 제공합니다.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {authorMode === 'edit' && (
            <>
              <button
                type="button"
                onClick={() => void handleDuplicate(target)}
                className="flex items-center gap-1.5 rounded-lg bg-surface-700 px-3 py-2 text-sm text-surface-200 transition-colors hover:bg-surface-600"
              >
                <Copy className="h-4 w-4" />
                {S.agents.duplicate}
              </button>
              <button
                type="button"
                onClick={() => void handleExport(target)}
                className="flex items-center gap-1.5 rounded-lg bg-surface-700 px-3 py-2 text-sm text-surface-200 transition-colors hover:bg-surface-600"
              >
                <Download className="h-4 w-4" />
                {S.agents.export_}
              </button>
              {!target.builtin && (
                <button
                  type="button"
                  onClick={() => setDeleteTarget(target)}
                  className="flex items-center gap-1.5 rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-400 transition-colors hover:bg-red-500/20"
                >
                  <Trash2 className="h-4 w-4" />
                  {S.agents.delete_}
                </button>
              )}
            </>
          )}
          {rawDirty && (
            <button
              type="button"
              onClick={() => {
                setEditRawMd(rawPreview);
                setRawDirty(false);
              }}
              className="rounded-lg bg-surface-700 px-3 py-2 text-sm text-surface-200 transition-colors hover:bg-surface-600"
            >
              폼 기준으로 raw 다시 생성
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`relative ${mode === 'list' ? 'page-container-wide' : 'page-container-compact'}`}>
      {toast && (
        <div className={`fixed right-4 top-16 z-50 rounded-full border px-4 py-2 text-sm shadow-lg backdrop-blur-xl ${
          toast.type === 'success'
            ? 'border-emerald-500/25 bg-emerald-500/12 text-emerald-100'
            : 'border-amber-500/25 bg-amber-500/12 text-amber-100'
        }`}
        >
          {toast.message}
        </div>
      )}

      <input
        ref={importInputRef}
        type="file"
        accept=".md"
        className="hidden"
        onChange={handleImportFile}
      />

      <Modal open={createChoiceOpen} onClose={() => setCreateChoiceOpen(false)} maxWidth="max-w-lg">
        <div className="space-y-5">
          <div>
            <h2 className="text-lg font-semibold text-surface-100">새 에이전트 시작 방식</h2>
            <p className="mt-1 text-sm text-surface-500">
              직접 작성하거나, AI 초안으로 시작한 뒤 맡길 논문 범위와 답변 톤을 다듬을 수 있습니다.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <button
              type="button"
              onClick={() => enterCreate('direct')}
              className="rounded-2xl border border-surface-700 bg-surface-900/60 p-4 text-left transition-colors hover:border-primary-500/30 hover:bg-surface-900"
            >
              <div className="mb-3 inline-flex rounded-full bg-surface-700 p-2 text-surface-200">
                <Edit3 className="h-4 w-4" />
              </div>
              <div className="text-sm font-semibold text-surface-100">직접 작성</div>
              <p className="mt-1 text-xs leading-relaxed text-surface-500">
                빈 폼에서 바로 시작합니다. 연구 분야와 답변 성향을 직접 정하는 방식입니다.
              </p>
            </button>
            <button
              type="button"
              onClick={() => enterCreate('ai')}
              className="rounded-2xl border border-primary-500/20 bg-primary-500/10 p-4 text-left transition-colors hover:bg-primary-500/15"
            >
              <div className="mb-3 inline-flex rounded-full bg-primary-500/15 p-2 text-primary-300">
                <Wand2 className="h-4 w-4" />
              </div>
              <div className="text-sm font-semibold text-surface-100">AI 초안으로 시작</div>
              <p className="mt-1 text-xs leading-relaxed text-surface-500">
                연구 분야 설명을 넣고 초안을 만든 뒤, 배정 기준과 톤을 검토합니다.
              </p>
            </button>
          </div>
        </div>
      </Modal>

      <Modal open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} maxWidth="max-w-md">
        <div className="space-y-5">
          <div className="flex items-start gap-3">
            <div className="rounded-full bg-red-500/10 p-2 text-red-400">
              <Trash2 className="h-5 w-5" />
            </div>
            <div>
              <p className="font-semibold text-surface-100">{S.agents.confirmDelete}</p>
              <p className="mt-1 text-sm text-surface-500">
                {deleteTarget ? agentDisplayName(deleteTarget) : ''}
              </p>
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDeleteTarget(null)}
              className="rounded-lg bg-surface-700 px-4 py-2 text-sm text-surface-200 transition-colors hover:bg-surface-600"
            >
              {S.agents.cancel}
            </button>
            <button
              type="button"
              onClick={() => void confirmDelete()}
              className="rounded-lg bg-red-500 px-4 py-2 text-sm text-white transition-colors hover:bg-red-600"
            >
              {S.agents.delete_}
            </button>
          </div>
        </div>
      </Modal>

      {mode === 'list' && (
        <>
          <section className="archive-panel panel-compact mb-4">
            <div className="page-header-dense">
              <div>
                <div className="archive-kicker">{S.agents.heroKicker}</div>
                <h1 className="mt-2 text-[1.8rem] font-semibold tracking-[-0.05em] text-surface-100">{S.agents.title}</h1>
                <p className="mt-2 text-sm leading-6 text-surface-400">{S.agents.heroBody}</p>
                <div className="page-status-strip mt-3">
                  <span className="archive-inline-status archive-inline-status-muted">
                    {S.agents.summaryAgents} {agents.length}
                  </span>
                  <span className="archive-inline-status archive-inline-status-muted">
                    {S.agents.summaryBuiltin} {builtinCount}
                  </span>
                  <span className="archive-inline-status archive-inline-status-muted">
                    {S.agents.summaryActive} {activeCount}
                  </span>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={handleImportClick}
                  className="flex items-center gap-1.5 rounded-full border border-surface-700 bg-surface-900/70 px-4 py-2.5 text-sm text-surface-200 transition-colors hover:border-surface-500 hover:bg-surface-900"
                >
                  <Upload className="h-4 w-4" />
                  {S.agents.import_}
                </button>
                <button
                  type="button"
                  onClick={() => setCreateChoiceOpen(true)}
                  className="flex items-center gap-1.5 rounded-full bg-primary-500 px-5 py-2.5 text-sm font-medium text-black transition-colors hover:bg-primary-400"
                >
                  <Plus className="h-4 w-4" />
                  {S.agents.createNew}
                </button>
              </div>
            </div>
          </section>

          {loading ? (
            <div className="flex items-center justify-center py-24 text-sm text-surface-500">불러오는 중...</div>
          ) : agents.length === 0 ? (
            <div className="archive-panel flex flex-col items-center justify-center gap-3 px-6 py-20 text-center">
              <p className="text-lg font-semibold text-surface-200">{S.agents.registryEmptyTitle}</p>
              <p className="max-w-md text-sm leading-7 text-surface-500">{S.agents.registryEmptyBody}</p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => enterCreate('direct')}
                  className="btn-secondary"
                >
                  {S.agents.createDirect}
                </button>
                <button
                  type="button"
                  onClick={() => enterCreate('ai')}
                  className="btn-primary"
                >
                  {S.agents.createAi}
                </button>
              </div>
            </div>
          ) : (
            <section className="archive-panel panel-compact">
              <div className="mb-4">
                <div className="archive-kicker">{S.agents.registryTitle}</div>
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                {agents.map((agent) => (
                  <div
                    key={agent.name}
                    className="rounded-[24px] border border-surface-800/80 bg-surface-950/55 p-5 transition-colors hover:border-surface-700"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex min-w-0 items-center gap-3">
                        <AgentAvatar name={agentDisplayName(agent)} color={agent.color} size="sm" />
                        <div className="min-w-0">
                          <div className="truncate text-base font-semibold tracking-[-0.03em] text-surface-100">
                            {agentDisplayName(agent)}
                          </div>
                          <div className="mt-1 truncate text-xs text-surface-500">{agent.name}</div>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <MetaBadge tone={agent.builtin ? 'warning' : 'neutral'}>
                          {agent.builtin ? '기본' : '사용자'}
                        </MetaBadge>
                        <MetaBadge tone={agent.enabled ? 'success' : 'neutral'}>
                          {agent.enabled ? '활성' : '비활성'}
                        </MetaBadge>
                      </div>
                    </div>
                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.2em] text-surface-600">담당 분야</div>
                        <div className="mt-2 text-sm text-surface-200">
                          {agent.domain_display_ko || agent.domain_display || agent.domain || '미정'}
                        </div>
                      </div>
                      <div>
                        <div className="text-[11px] uppercase tracking-[0.2em] text-surface-600">응답 태도</div>
                        <div className="mt-2 line-clamp-2 text-sm text-surface-400">
                          {agent.personality || '설명 없음'}
                        </div>
                      </div>
                    </div>
                    <div className="mt-5 flex items-center justify-between gap-3 border-t border-surface-800/80 pt-4">
                      <p className="line-clamp-2 text-xs leading-6 text-surface-500">
                        {agent.quote || '대표 문장이 아직 비어 있습니다.'}
                      </p>
                      <button
                        type="button"
                        onClick={() => void enterEdit(agent)}
                        className="flex shrink-0 items-center gap-1.5 rounded-full border border-surface-700 bg-surface-900/70 px-4 py-2 text-sm text-surface-200 transition-colors hover:border-surface-500 hover:bg-surface-900"
                      >
                        <Edit3 className="h-4 w-4" />
                        {S.agents.edit}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}

      {mode === 'author' && (
        <>
          <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              <button
                type="button"
                onClick={() => setMode('list')}
                className="mt-0.5 flex items-center gap-1.5 text-sm text-surface-400 transition-colors hover:text-surface-200"
              >
                <ChevronLeft className="h-4 w-4" />
                {S.agents.back}
              </button>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-xl font-bold text-surface-100">{authorTitle}</h1>
                  {isEditingBuiltin && <MetaBadge tone="warning">기본 에이전트</MetaBadge>}
                  {!isEditingBuiltin && authorMode === 'edit' && <MetaBadge>사용자 에이전트</MetaBadge>}
                  <MetaBadge tone={formData.enabled ? 'success' : 'neutral'}>
                    {formData.enabled ? '활성 상태로 저장' : '비활성 상태로 저장'}
                  </MetaBadge>
                  {generatedDraft && <MetaBadge tone="accent">AI 초안 적용됨</MetaBadge>}
                  {saveUsesRaw && <MetaBadge tone="warning">raw draft 저장 중</MetaBadge>}
                </div>
                <p className="mt-1 text-sm text-surface-500">
                  {isAdvancedStep
                    ? '고급 편집에서는 프롬프트와 raw markdown를 다룹니다. 기본 구조 확인 후에만 수정하세요.'
                    : '이 에이전트가 맡을 논문 범위와 답변 톤을 먼저 정리한 뒤 저장하세요.'}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setAuthorStep(isAdvancedStep ? 'basic' : 'advanced')}
                className={`rounded-lg px-3 py-2 text-sm transition-colors ${
                  isAdvancedStep
                    ? 'bg-surface-700 text-surface-200 hover:bg-surface-600'
                    : 'border border-primary-500/20 bg-primary-500/10 text-primary-300 hover:bg-primary-500/20'
                }`}
              >
                {isAdvancedStep ? '기본 편집으로 돌아가기' : '고급 편집 열기'}
              </button>
              <button
                type="button"
                onClick={() => setMode('list')}
                className="rounded-lg bg-surface-700 px-3 py-2 text-sm text-surface-200 transition-colors hover:bg-surface-600"
              >
                {S.agents.cancel}
              </button>
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={submitting || authorLoading}
                className="flex items-center gap-1.5 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-60"
              >
                <Check className="h-4 w-4" />
                {submitting ? '...' : saveUsesRaw ? '검토 후 저장' : authorMode === 'create' ? S.agents.create : S.agents.save}
              </button>
            </div>
          </div>

          {authorLoading ? (
            <div className="flex items-center justify-center rounded-2xl border border-surface-700/50 bg-surface-800 p-12 text-sm text-surface-500">
              불러오는 중...
            </div>
          ) : (
            <>
              {isEditingBuiltin && (
                <div className="mb-4 flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  기본 에이전트를 저장하면 사용자 정의 override가 생성됩니다.
                </div>
              )}

              {saveUsesRaw && !isAdvancedStep && (
                <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-amber-500/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
                  <span>현재 저장 기준은 raw markdown입니다. 폼 변경만으로는 raw draft가 바뀌지 않습니다.</span>
                  <button
                    type="button"
                    onClick={() => {
                      setEditRawMd(rawPreview);
                      setRawDirty(false);
                    }}
                    className="shrink-0 rounded-lg bg-amber-500/15 px-3 py-1.5 text-xs text-amber-100 transition-colors hover:bg-amber-500/25"
                  >
                    폼 기준으로 되돌리기
                  </button>
                </div>
              )}

              {!isAdvancedStep && (
                <div className="space-y-6">
                  {isCreateMode && createStartMode === 'ai' && (
                    <div className="rounded-2xl border border-primary-500/15 bg-primary-500/8 p-5">
                      <div className="mb-4 flex items-start gap-3">
                        <div className="rounded-full bg-primary-500/15 p-2 text-primary-300">
                          <Sparkles className="h-4 w-4" />
                        </div>
                        <div>
                          <div className="text-sm font-semibold text-surface-100">AI 초안은 시작점으로만 사용합니다</div>
                          <p className="mt-1 text-xs leading-relaxed text-surface-500">
                            연구 분야를 설명하면 초안을 만들고, 이후 맡길 논문 범위와 답변 톤을 직접 검토합니다.
                          </p>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_14rem_10rem]">
                        <Field label={S.agents.domainDescription + ' *'} help={S.agents.domainDescriptionHelp}>
                          <input
                            className={inputCls}
                            value={generateInput.domain_description}
                            onChange={(e) => setGenerateInput((prev) => ({ ...prev, domain_description: e.target.value }))}
                            placeholder={S.agents.domainDescriptionPlaceholder}
                          />
                        </Field>
                        <Field label={S.agents.personalityHint}>
                          <input
                            className={inputCls}
                            value={generateInput.personality_hint}
                            onChange={(e) => setGenerateInput((prev) => ({ ...prev, personality_hint: e.target.value }))}
                            placeholder={S.agents.personalityHintPlaceholder}
                          />
                        </Field>
                        <Field label={S.agents.color}>
                          <ColorPicker
                            value={generateInput.color}
                            onChange={(color) => setGenerateInput((prev) => ({ ...prev, color }))}
                          />
                        </Field>
                      </div>

                      <div className="mt-4 flex justify-end">
                        <button
                          type="button"
                          onClick={() => void handleGenerateDraft()}
                          disabled={generating}
                          className="flex items-center gap-2 rounded-lg bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600 disabled:opacity-60"
                        >
                          {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                          {generating ? S.agents.aiGenerating : 'AI 초안 적용'}
                        </button>
                      </div>
                    </div>
                  )}

                  {generatedDraft && (
                    <div className="flex items-center justify-between gap-3 rounded-lg border border-primary-500/20 bg-primary-500/10 px-4 py-3 text-sm text-primary-300">
                      <span>AI 초안이 반영되었습니다. 저장 전 미리보기와 맡길 논문 범위를 먼저 확인하세요.</span>
                      <button
                        type="button"
                        onClick={() => void handleGenerateDraft()}
                        disabled={generating}
                        className="shrink-0 rounded-lg bg-primary-500/15 px-3 py-1.5 text-xs text-primary-200 transition-colors hover:bg-primary-500/25 disabled:opacity-60"
                      >
                        다시 생성
                      </button>
                    </div>
                  )}

                  <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
                    <div className="space-y-6">
                      <Section
                        title={S.agents.stepIdentity}
                        body="앱에서 보일 이름, 첫인상, 기본 상태를 정합니다. 연구자가 바로 이해할 수 있는 이름과 대사를 먼저 맞추세요."
                      >
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                          <Field label={S.agents.name} help={S.agents.nameHelp}>
                            <input
                              className={`${inputCls} ${authorMode === 'edit' ? 'cursor-not-allowed opacity-70' : ''}`}
                              value={formData.name}
                              onChange={(e) => setField('name', sanitizeAgentName(e.target.value))}
                              placeholder="my_agent"
                              disabled={authorMode === 'edit'}
                            />
                          </Field>
                          <Field label={S.agents.displayName}>
                            <input
                              className={inputCls}
                              value={formData.display_name}
                              onChange={(e) => setField('display_name', e.target.value)}
                              placeholder="My Agent"
                            />
                          </Field>
                        </div>
                        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                          <Field label={S.agents.displayNameKo}>
                            <input
                              className={inputCls}
                              value={formData.display_name_ko}
                              onChange={(e) => setField('display_name_ko', e.target.value)}
                              placeholder="나의 에이전트"
                            />
                          </Field>
                          <Field label={S.agents.color}>
                            <ColorPicker value={formData.color} onChange={(color) => setField('color', color)} />
                          </Field>
                        </div>
                        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
                          <Field label={S.agents.personality} help="답변 스타일을 한 문장으로 적으세요. 연구자가 받게 될 톤을 결정합니다.">
                            <input
                              className={inputCls}
                              value={formData.personality}
                              onChange={(e) => setField('personality', e.target.value)}
                              placeholder="직설적이지만 설명은 차분하게 정리하는 톤"
                            />
                          </Field>
                          <Field label={S.agents.quote} help="첫 응답에서 느껴질 대표 문장입니다. 너무 과장된 말보다 이해하기 쉬운 표현이 좋습니다.">
                            <input
                              className={inputCls}
                              value={formData.quote}
                              onChange={(e) => setField('quote', e.target.value)}
                              placeholder="핵심부터 빠르게 정리해볼게요."
                            />
                          </Field>
                        </div>
                        <div className="mt-4 rounded-xl border border-surface-700/50 bg-surface-900/55 p-4">
                          <Toggle
                            checked={formData.enabled}
                            onChange={(checked) => setField('enabled', checked)}
                            label="활성 상태로 저장"
                            description={formData.enabled ? '저장 후 바로 배정 후보로 사용됩니다.' : '저장되지만 새 논문 배정에는 사용되지 않습니다.'}
                          />
                        </div>
                      </Section>

                      <Section
                        title={S.agents.stepDomain}
                        body="어떤 논문을 이 에이전트에게 맡길지 정합니다. 여기서 정한 도메인과 키워드가 배정 결과에 직접 영향을 줍니다."
                      >
                        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                          <Field label={S.agents.domain}>
                            <input
                              className={inputCls}
                              value={formData.domain}
                              onChange={(e) => setField('domain', e.target.value.toLowerCase())}
                              placeholder="optics"
                            />
                          </Field>
                          <Field label={S.agents.domainDisplay}>
                            <input
                              className={inputCls}
                              value={formData.domain_display}
                              onChange={(e) => setField('domain_display', e.target.value)}
                              placeholder="Optics"
                            />
                          </Field>
                          <Field label={S.agents.domainDisplayKo}>
                            <input
                              className={inputCls}
                              value={formData.domain_display_ko}
                              onChange={(e) => setField('domain_display_ko', e.target.value)}
                              placeholder="광학"
                            />
                          </Field>
                        </div>
                        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
                          <Field label={S.agents.keywords} help="넓은 범위의 배정 신호입니다. 많을수록 범위가 흐려질 수 있으니 핵심 용어만 남기세요.">
                            <TagInput
                              tags={formData.keywords}
                              onChange={(tags) => setField('keywords', tags)}
                              placeholder="laser, photon, resonator"
                            />
                          </Field>
                          <Field label={S.agents.weightedKeywords} help="강한 배정 신호입니다. 이 분야를 확실히 가르는 용어만 넣는 편이 안전합니다.">
                            <TagInput
                              tags={formData.weighted_keywords}
                              onChange={(tags) => setField('weighted_keywords', tags)}
                              placeholder="optical fiber, waveguide"
                            />
                          </Field>
                        </div>
                      </Section>

                      <Section
                        title={S.agents.stepParameters}
                        body="답변에서 특히 챙길 실험 파라미터를 정합니다. 재현성 요약과 레시피 추출의 강조점이 여기서 결정됩니다."
                      >
                        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_12rem]">
                          <Field label={S.agents.recipeParameters} help="실험 조건, 장비 설정, 재료 수치처럼 반복해서 확인할 항목을 넣으세요.">
                            <TagInput
                              tags={formData.recipe_parameters}
                              onChange={(tags) => setField('recipe_parameters', tags)}
                              placeholder="wavelength, power, annealing_temperature"
                            />
                          </Field>
                          <Field label={S.agents.model}>
                            <select
                              className={inputCls}
                              value={formData.model}
                              onChange={(e) => setField('model', e.target.value)}
                            >
                              <option value="gemini-pro">Gemini Pro</option>
                              <option value="gemini-flash">Gemini Flash</option>
                            </select>
                          </Field>
                        </div>
                      </Section>

                      <Section
                        title={S.agents.stepPreview}
                        body="저장 전에 앱에서 어떻게 보일지, 어떤 논문을 맡을지, 어떤 톤으로 답할지를 빠르게 확인합니다."
                      >
                        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                          <div className="rounded-xl border border-surface-700/50 bg-surface-900/55 p-4">
                            <div className="mb-2 text-2xs uppercase tracking-[0.16em] text-surface-500">Card Preview</div>
                            <div className="flex items-center gap-3">
                              <AgentAvatar name={previewName} color={formData.color} size="lg" />
                              <div className="min-w-0">
                                <p className="truncate font-semibold text-surface-100">{previewName}</p>
                                <p className="truncate text-xs text-surface-500">{previewDomain}</p>
                              </div>
                            </div>
                            <p className="mt-3 text-sm italic text-surface-400">
                              "{formData.quote || '대표 대사를 아직 정하지 않았습니다.'}"
                            </p>
                            <div className="mt-3">
                              <MetaBadge tone={formData.enabled ? 'success' : 'neutral'}>
                                {formData.enabled ? '활성 상태로 저장' : '비활성 상태로 저장'}
                              </MetaBadge>
                            </div>
                          </div>

                          <div className="rounded-xl border border-surface-700/50 bg-surface-900/55 p-4">
                            <div className="mb-2 text-2xs uppercase tracking-[0.16em] text-surface-500">Routing Summary</div>
                            <p className="text-sm leading-relaxed text-surface-300">{routingSummary}</p>
                          </div>

                          <div className="rounded-xl border border-surface-700/50 bg-surface-900/55 p-4">
                            <div className="mb-2 text-2xs uppercase tracking-[0.16em] text-surface-500">Tone Preview</div>
                            <p className="text-sm leading-relaxed text-surface-300">{tonePreview}</p>
                            <div className="mt-4 text-2xs uppercase tracking-[0.16em] text-surface-500">Output Focus</div>
                            <p className="mt-2 text-sm leading-relaxed text-surface-300">{outputSummary}</p>
                          </div>
                        </div>
                      </Section>
                    </div>

                    <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
                      <div className="rounded-2xl border border-surface-700/50 bg-surface-800/85 p-5">
                        <div className="mb-2 text-2xs uppercase tracking-[0.18em] text-surface-500">Quick Checks</div>
                        <div className="space-y-3 text-sm">
                          <div className="rounded-xl bg-surface-900/60 px-3 py-3">
                            <div className="text-2xs uppercase tracking-[0.16em] text-surface-500">이름</div>
                            <div className="mt-1 text-surface-200">{previewName}</div>
                          </div>
                          <div className="rounded-xl bg-surface-900/60 px-3 py-3">
                            <div className="text-2xs uppercase tracking-[0.16em] text-surface-500">도메인</div>
                            <div className="mt-1 text-surface-200">{formData.domain || '미정'}</div>
                          </div>
                          <div className="rounded-xl bg-surface-900/60 px-3 py-3">
                            <div className="text-2xs uppercase tracking-[0.16em] text-surface-500">상태</div>
                            <div className="mt-1 text-surface-200">{formData.enabled ? '활성' : '비활성'}</div>
                          </div>
                          <div className="rounded-xl bg-surface-900/60 px-3 py-3">
                            <div className="text-2xs uppercase tracking-[0.16em] text-surface-500">레시피 포커스</div>
                            <div className="mt-1 text-surface-200">{formData.recipe_parameters.length}개 설정</div>
                          </div>
                        </div>
                      </div>
                      {renderAuthorActions()}
                    </div>
                  </div>
                </div>
              )}

              {isAdvancedStep && (
                <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
                  <div className="rounded-2xl border border-surface-700/50 bg-surface-800/85 p-5">
                    <div className="mb-5">
                      <h2 className="text-sm font-semibold text-surface-100">고급 편집</h2>
                      <p className="mt-1 text-xs leading-relaxed text-surface-500">
                        프롬프트 조정과 raw markdown 편집은 고급 단계입니다. 기본 구조 확인 후에만 수정하세요.
                      </p>
                    </div>

                    <div className="flex items-center gap-1 rounded-lg border border-surface-700 bg-surface-900 p-1">
                      <button
                        type="button"
                        onClick={() => setExpertView('prompts')}
                        className={`rounded-md px-3 py-1.5 text-xs transition-colors ${
                          expertView === 'prompts'
                            ? 'bg-primary-500/20 text-primary-300'
                            : 'text-surface-400 hover:text-surface-200'
                        }`}
                      >
                        프롬프트
                      </button>
                      <button
                        type="button"
                        onClick={() => setExpertView('raw')}
                        className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs transition-colors ${
                          expertView === 'raw'
                            ? 'bg-primary-500/20 text-primary-300'
                            : 'text-surface-400 hover:text-surface-200'
                        }`}
                      >
                        <Code className="h-3.5 w-3.5" />
                        {S.agents.rawMarkdown}
                      </button>
                    </div>

                    {expertView === 'prompts' ? (
                      <div className="mt-4">
                        <div className="mb-3 flex gap-1 rounded-lg border border-surface-700 bg-surface-900 p-1">
                          {PROMPT_TABS.map((tab) => (
                            <button
                              key={tab.key}
                              type="button"
                              onClick={() => setExpertPromptTab(tab.key)}
                              className={`flex-1 rounded-md py-1.5 text-xs font-medium transition-colors ${
                                expertPromptTab === tab.key
                                  ? 'bg-primary-500/20 text-primary-300'
                                  : 'text-surface-400 hover:text-surface-200'
                              }`}
                            >
                              {tab.label}
                            </button>
                          ))}
                        </div>
                        <textarea
                          className={`${textareaCls} min-h-[320px]`}
                          value={formData.prompts[expertPromptTab]}
                          onChange={(e) => setField('prompts', { ...formData.prompts, [expertPromptTab]: e.target.value })}
                          placeholder="이 단계의 고급 프롬프트를 입력하세요"
                        />
                      </div>
                    ) : (
                      <div className="mt-4">
                        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                          <p className="text-xs leading-relaxed text-surface-500">
                            폼 구조를 우회하는 편집입니다. 검토 후 저장하세요.
                          </p>
                          <button
                            type="button"
                            onClick={() => {
                              setEditRawMd(rawPreview);
                              setRawDirty(false);
                            }}
                            className="rounded-lg bg-surface-700 px-3 py-1.5 text-xs text-surface-200 transition-colors hover:bg-surface-600"
                          >
                            폼 기준으로 다시 생성
                          </button>
                        </div>
                        <textarea
                          className={`${textareaCls} min-h-[420px] font-mono`}
                          value={editRawMd}
                          onChange={(e) => {
                            setEditRawMd(e.target.value);
                            setRawDirty(true);
                          }}
                          placeholder="# Agent markdown content..."
                        />
                      </div>
                    )}
                  </div>

                  <div className="space-y-4 xl:sticky xl:top-6 xl:self-start">
                    <div className="rounded-2xl border border-surface-700/50 bg-surface-800/85 p-5">
                      <div className="mb-2 text-2xs uppercase tracking-[0.18em] text-surface-500">Advanced Checks</div>
                      <div className="space-y-3 text-sm">
                        <div className="rounded-xl bg-surface-900/60 px-3 py-3">
                          <div className="text-2xs uppercase tracking-[0.16em] text-surface-500">현재 편집</div>
                          <div className="mt-1 text-surface-200">
                            {expertView === 'raw' ? 'raw markdown' : PROMPT_TABS.find((tab) => tab.key === expertPromptTab)?.label}
                          </div>
                        </div>
                        <div className="rounded-xl bg-surface-900/60 px-3 py-3">
                          <div className="text-2xs uppercase tracking-[0.16em] text-surface-500">저장 기준</div>
                          <div className="mt-1 text-surface-200">{saveUsesRaw ? 'raw draft' : '폼 구조'}</div>
                        </div>
                        <div className="rounded-xl bg-surface-900/60 px-3 py-3">
                          <div className="text-2xs uppercase tracking-[0.16em] text-surface-500">배정 도메인</div>
                          <div className="mt-1 text-surface-200">{previewDomain}</div>
                        </div>
                      </div>
                    </div>
                    {renderAuthorActions()}
                  </div>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
