import { getApiBase } from '@/lib/api';

// ---------------------------------------------------------------------------
// Agent metadata
// ---------------------------------------------------------------------------

export interface AgentMeta {
  key: string;
  name: string;
  display_name: string;
  display_name_ko: string;
  nameKo: string;
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
  builtin: boolean;
  prompts: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Color utilities (inline styles, since hex colors are dynamic)
// ---------------------------------------------------------------------------

function hexToRgba(hex: string, alpha: number): string {
  const cleaned = hex.replace('#', '');
  const r = parseInt(cleaned.substring(0, 2), 16);
  const g = parseInt(cleaned.substring(2, 4), 16);
  const b = parseInt(cleaned.substring(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function agentBgStyle(color: string, opacity = 0.1): React.CSSProperties {
  return { backgroundColor: hexToRgba(color, opacity) };
}

export function agentBorderStyle(color: string, opacity = 0.2): React.CSSProperties {
  return { borderColor: hexToRgba(color, opacity) };
}

// ---------------------------------------------------------------------------
// Module-level cache populated by fetchAllAgents()
// ---------------------------------------------------------------------------

const _agentCache: Map<string, AgentMeta> = new Map();

/** Fetch all agents from the backend and populate the cache. */
export async function fetchAllAgents(): Promise<AgentMeta[]> {
  const url = `${getApiBase()}/agents`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch agents: ${res.statusText}`);
  }
  const data: AgentRaw[] = await res.json();
  _agentCache.clear();
  const agents = data.map(rawToMeta);
  for (const agent of agents) {
    _agentCache.set(agent.key, agent);
  }
  return agents;
}

interface AgentRaw {
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
  builtin: boolean;
  prompts: Record<string, string>;
}

function rawToMeta(raw: AgentRaw): AgentMeta {
  return {
    key: raw.name,
    name: raw.display_name,
    display_name: raw.display_name,
    display_name_ko: raw.display_name_ko,
    nameKo: raw.display_name_ko,
    personality: raw.personality,
    quote: raw.quote,
    color: raw.color,
    domain: raw.domain,
    domain_display: raw.domain_display,
    domain_display_ko: raw.domain_display_ko,
    keywords: raw.keywords,
    weighted_keywords: raw.weighted_keywords,
    recipe_parameters: raw.recipe_parameters,
    model: raw.model,
    enabled: raw.enabled,
    builtin: raw.builtin,
    prompts: raw.prompts,
  };
}

// ---------------------------------------------------------------------------
// Fallback agent for unknown domains
// ---------------------------------------------------------------------------

export const FALLBACK_AGENT: AgentMeta = {
  key: 'unknown',
  name: '알 수 없는 에이전트',
  display_name: 'Unknown Agent',
  display_name_ko: '알 수 없음',
  nameKo: '알 수 없음',
  personality: '알 수 없는 분야',
  quote: '분석 준비 중입니다.',
  color: '#6b7280',
  domain: 'unknown',
  domain_display: 'Unknown',
  domain_display_ko: '알 수 없음',
  keywords: [],
  weighted_keywords: [],
  recipe_parameters: [],
  model: '',
  enabled: false,
  builtin: false,
  prompts: {},
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Get agent metadata by agent name (e.g. 'photon', 'cell'). Returns null if not in cache. */
export function getAgentMeta(name?: string): AgentMeta | null {
  if (!name) return null;
  return _agentCache.get(name.toLowerCase()) ?? null;
}

/** Get agent metadata with fallback for unknown agents. */
export function getAgentMetaOrFallback(name?: string): AgentMeta {
  if (!name) return FALLBACK_AGENT;
  return _agentCache.get(name.toLowerCase()) ?? FALLBACK_AGENT;
}

/** Get all agents from the cache. */
export function getAllAgents(): AgentMeta[] {
  return Array.from(_agentCache.values());
}
