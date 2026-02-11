import photonImg from '@/assets/agents/photon.png';
import bioImg from '@/assets/agents/bio.png';
import neuralImg from '@/assets/agents/neural.png';
import circuitImg from '@/assets/agents/circuit.png';

// ---------------------------------------------------------------------------
// Agent metadata
// ---------------------------------------------------------------------------

export interface AgentMeta {
  key: string;
  name: string;
  nameKo: string;
  personality: string;
  quote: string;
  color: string;
  bgColor: string;
  borderColor: string;
  image: string;
}

const AGENTS: Record<string, AgentMeta> = {
  photon: {
    key: 'photon',
    name: 'Photon',
    nameKo: '포톤',
    personality: '직설적인 광학 전문가',
    quote: '빛은 거짓말을 안 해.',
    color: 'text-red-400',
    bgColor: 'bg-red-500/10',
    borderColor: 'border-red-500/20',
    image: photonImg,
  },
  cell: {
    key: 'cell',
    name: 'Cell',
    nameKo: '셀',
    personality: '꼼꼼한 바이오 전문가',
    quote: '세포 하나도 놓치지 마.',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
    borderColor: 'border-emerald-500/20',
    image: bioImg,
  },
  neural: {
    key: 'neural',
    name: 'Neural',
    nameKo: '뉴럴',
    personality: '분석적인 AI 전문가',
    quote: '데이터가 답을 알고 있어.',
    color: 'text-purple-400',
    bgColor: 'bg-purple-500/10',
    borderColor: 'border-purple-500/20',
    image: neuralImg,
  },
  circuit: {
    key: 'circuit',
    name: 'Circuit',
    nameKo: '서킷',
    personality: '실용적인 전자공학 전문가',
    quote: '회로는 정직하거든.',
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/10',
    borderColor: 'border-yellow-500/20',
    image: circuitImg,
  },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Get agent metadata by agent name (e.g. 'photon', 'cell') */
export function getAgentMeta(name?: string): AgentMeta | null {
  if (!name) return null;
  return AGENTS[name.toLowerCase()] ?? null;
}

/** Get all agents */
export function getAllAgents(): AgentMeta[] {
  return Object.values(AGENTS);
}
