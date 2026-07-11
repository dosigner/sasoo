// AgentAvatar — circular avatar showing first letter of agent name on a colored background

interface AgentAvatarProps {
  name: string;   // display_name_ko or name
  color: string;  // hex color like "#ef4444"
  size?: 'sm' | 'md' | 'lg';
}

const SIZE_CLASSES = {
  sm: 'w-8 h-8',
  md: 'w-10 h-10',
  lg: 'w-14 h-14',
} as const;

const FONT_CLASSES = {
  sm: 'text-xs',
  md: 'text-sm',
  lg: 'text-xl',
} as const;

export default function AgentAvatar({ name, color, size = 'md' }: AgentAvatarProps) {
  const initial = name ? name.charAt(0).toUpperCase() : '?';

  return (
    <div
      className={`${SIZE_CLASSES[size]} rounded-full flex items-center justify-center shrink-0`}
      style={{ backgroundColor: color }}
    >
      <span className={`${FONT_CLASSES[size]} font-semibold text-white select-none`}>
        {initial}
      </span>
    </div>
  );
}
