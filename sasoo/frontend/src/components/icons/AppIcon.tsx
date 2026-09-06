import type { LucideProps } from 'lucide-react';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Bot,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
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
  Sparkles,
  Square,
  Sun,
  Tag,
  Trash2,
  AlertTriangle,
  Upload,
  UserRound,
  X,
  DollarSign,
} from 'lucide-react';

export type AppIconName =
  | 'upload'
  | 'library'
  | 'agents'
  | 'profile'
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
  | 'spinner';

export interface AppIconProps extends Omit<LucideProps, 'ref'> {
  name: AppIconName;
}

const ICON_MAP = {
  upload: Upload,
  library: BookOpen,
  // agents는 분석 에이전트(AI), profile은 사용자 자신이다. 같은 아이콘을 쓰지 않는다.
  agents: Bot,
  profile: UserRound,
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
} satisfies Record<AppIconName, React.ComponentType<LucideProps>>;

export default function AppIcon({ name, className, ...props }: AppIconProps) {
  const Icon = ICON_MAP[name];
  return <Icon className={className} {...props} />;
}
