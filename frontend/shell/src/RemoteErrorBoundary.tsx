import React from "react";

interface Props {
  children: React.ReactNode;
  label: string;
  onRetry: () => void;
}

interface State {
  hasError: boolean;
}

// Catches both React render errors and loadRemoteModule's rejected promise
// (React.lazy turns a rejected dynamic-import promise into a thrown error
// during Suspense render, which a class boundary catches normally). Retry
// must force a *fresh* React.lazy() call — its promise is cached forever
// per call site — so the caller passes an onRetry that bumps a nonce driving
// a new useMemo(() => React.lazy(...), [nonce]).
export class RemoteErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error(`[RemoteErrorBoundary] ${this.props.label}:`, error);
  }

  handleRetry = () => {
    this.props.onRetry();
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div role="alert" style={{ padding: 16, border: "1px solid #d6d9e0", borderRadius: 6 }}>
          <p>The {this.props.label} section is temporarily unavailable.</p>
          <button onClick={this.handleRetry}>Retry</button>
        </div>
      );
    }
    return this.props.children;
  }
}
