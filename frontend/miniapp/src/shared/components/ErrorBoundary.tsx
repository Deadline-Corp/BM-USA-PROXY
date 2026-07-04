import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Top-level error boundary. Catches render-time errors anywhere below it and
 * shows a minimal fallback with a reload button instead of a blank screen.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error("ErrorBoundary caught an error:", error, info);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-app px-6 text-center">
          <p className="text-[13.5px] font-medium text-text">Something went wrong. Please reload.</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg border border-border bg-surface px-4 py-2 text-[13px] font-medium text-text"
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}