import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { Link } from 'react-router-dom';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

/**
 * Error Boundary Component
 *
 * Catches rendering errors, lifecycle errors, and constructor errors
 * in child components and displays a user-friendly fallback UI.
 */
class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    // Update state so the next render will show the fallback UI
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log error details to console with full stack trace
    console.error('ErrorBoundary caught an error:', error);
    console.error('Component stack trace:', errorInfo.componentStack);

    this.setState({
      error,
      errorInfo,
    });
  }

  handleReset = (): void => {
    // Reset error state to retry rendering
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    const { hasError, error } = this.state;
    const { children, fallback } = this.props;

    if (hasError) {
      // If custom fallback is provided, use it
      if (fallback) {
        return fallback;
      }

      // Default fallback UI
      return (
        <div className="flex h-full min-h-screen items-center justify-center bg-bg p-4">
          <div className="w-full max-w-md rounded-xl border border-border bg-surface p-8 shadow-xl">
            {/* Error Icon */}
            <div className="flex justify-center mb-6">
              <div className="w-16 h-16 rounded-full bg-danger/10 border border-danger/20 flex items-center justify-center">
                <AlertTriangle className="w-8 h-8 text-danger" />
              </div>
            </div>

            {/* Error Title */}
            <h1 className="mb-3 text-center text-xl font-semibold text-fg">
              오류가 발생했습니다
            </h1>

            {/* Error Message */}
            <p className="mb-6 break-words text-center text-sm text-fg-muted">
              {error?.message || '알 수 없는 오류가 발생했습니다.'}
            </p>

            {/* Action Buttons */}
            <div className="flex flex-col gap-3">
              {/* Retry Button */}
              <button
                onClick={this.handleReset}
                className="w-full px-4 py-2.5 bg-accent hover:bg-accent-hover active:bg-accent-hover text-accent-fg rounded-lg font-medium transition-colors duration-200 shadow-sm hover:shadow-md"
              >
                다시 시도
              </button>

              {/* Home Button */}
              <Link
                to="/"
                className="w-full rounded-lg border border-border bg-surface px-4 py-2.5 text-center font-medium text-fg transition-colors duration-200 hover:bg-surface-hover"
              >
                홈으로 돌아가기
              </Link>
            </div>

            {/* Developer Info (only in development) */}
            {process.env.NODE_ENV === 'development' && error && (
              <details className="mt-6 rounded-lg border border-border bg-bg p-4">
                <summary className="cursor-pointer text-xs font-medium text-fg-secondary hover:text-fg">
                  개발자 정보 (Development Only)
                </summary>
                <pre className="mt-3 max-h-40 overflow-auto text-2xs text-danger">
                  {error.stack}
                </pre>
              </details>
            )}
          </div>
        </div>
      );
    }

    return children;
  }
}

export default ErrorBoundary;
