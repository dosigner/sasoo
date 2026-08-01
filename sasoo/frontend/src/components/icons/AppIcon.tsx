import type { LucideProps } from 'lucide-react';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Atom,
  Bot,
  BookOpen,
  Brain,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircuitBoard,
  Clock3,
  Code,
  Dna,
  Download,
  Eye,
  EyeOff,
  FileSearch,
  FileText,
  Filter,
  FlaskConical,
  FolderOpen,
  Grid2x2,
  ImageIcon,
  Info,
  KeyRound,
  LayoutGrid,
  List,
  Loader2,
  Maximize2,
  MessageSquareText,
  Microscope,
  Minus,
  Moon,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Plus,
  Save,
  Search,
  Settings,
  Shapes,
  Sparkles,
  Square,
  Sun,
  Tag,
  Trash2,
  AlertTriangle,
  Upload,
  Waves,
  X,
  DollarSign,
} from 'lucide-react';

export type AppIconName =
  | 'upload'
  | 'library'
  | 'agents'
  | 'settings'
  | 'workbench'
  | 'back'
  | 'panel-open'
  | 'panel-close'
  | 'summary'
  | 'figures'
  | 'tables'
  | 'recipe'
  | 'experiment'
  | 'search'
  | 'grid'
  | 'list'
  | 'filter'
  | 'chevron-down'
  | 'chevron-left'
  | 'chevron-right'
  | 'more'
  | 'document'
  | 'delete'
  | 'clock'
  | 'tag'
  | 'close'
  | 'success'
  | 'error'
  | 'warning'
  | 'info'
  | 'save'
  | 'key'
  | 'eye'
  | 'eye-off'
  | 'folder'
  | 'sun'
  | 'moon'
  | 'dollar'
  | 'sparkles'
  | 'arrow-right'
  | 'chat'
  | 'download'
  | 'minimize'
  | 'plus'
  | 'maximize'
  | 'restore'
  | 'play'
  | 'stop'
  | 'spinner'
  | 'area-optics'
  | 'area-ai'
  | 'area-robotics'
  | 'area-electrical'
  | 'area-cs'
  | 'area-physics'
  | 'area-bio'
  | 'area-other';

export interface AppIconProps extends Omit<LucideProps, 'ref'> {
  name: AppIconName;
}

const ICON_MAP = {
  upload: Upload,
  library: BookOpen,
  agents: Bot,
  settings: Settings,
  workbench: Microscope,
  back: ArrowLeft,
  'panel-open': PanelLeftOpen,
  'panel-close': PanelLeftClose,
  summary: FileSearch,
  figures: ImageIcon,
  tables: LayoutGrid,
  recipe: FlaskConical,
  experiment: FlaskConical,
  search: Search,
  grid: LayoutGrid,
  list: List,
  filter: Filter,
  'chevron-down': ChevronDown,
  'chevron-left': ChevronLeft,
  'chevron-right': ChevronRight,
  more: MoreHorizontal,
  document: FileText,
  delete: Trash2,
  clock: Clock3,
  tag: Tag,
  close: X,
  success: Check,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
  save: Save,
  key: KeyRound,
  eye: Eye,
  'eye-off': EyeOff,
  folder: FolderOpen,
  sun: Sun,
  moon: Moon,
  dollar: DollarSign,
  sparkles: Sparkles,
  'arrow-right': ArrowRight,
  chat: MessageSquareText,
  download: Download,
  minimize: Minus,
  plus: Plus,
  maximize: Maximize2,
  restore: Grid2x2,
  play: Play,
  stop: Square,
  spinner: Loader2,
  // 연구 분야 아이콘. AreaPicker.tsx의 AREAS와 1:1 대응한다.
  'area-optics': Waves,
  'area-ai': Brain,
  'area-robotics': Bot,
  'area-electrical': CircuitBoard,
  'area-cs': Code,
  'area-physics': Atom,
  'area-bio': Dna,
  'area-other': Shapes,
} satisfies Record<AppIconName, React.ComponentType<LucideProps>>;

export default function AppIcon({ name, className, ...props }: AppIconProps) {
  const Icon = ICON_MAP[name];
  return <Icon className={className} {...props} />;
}
