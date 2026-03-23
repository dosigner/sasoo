import { MessageSquareText, X } from 'lucide-react';

interface ChatComposerFabProps {
  open: boolean;
  onClick: () => void;
}

export default function ChatComposerFab({ open, onClick }: ChatComposerFabProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`chat-launcher ${open ? 'chat-launcher-open' : ''}`}
      data-chat-launcher="true"
      aria-label={open ? '질의 패널 닫기' : '질의 패널 열기'}
      title={open ? '질의 패널 닫기' : '질의 패널 열기'}
    >
      {open ? <X className="h-4 w-4" /> : <MessageSquareText className="h-4 w-4" />}
      <span className="text-xs font-medium">{open ? '닫기' : '질문하기'}</span>
    </button>
  );
}
