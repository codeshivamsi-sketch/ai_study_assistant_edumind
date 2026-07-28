import React from "react";
import { loadRemoteModule } from "./utils/loadRemoteModule";
import { RemoteErrorBoundary } from "./RemoteErrorBoundary";

interface RemoteSectionProps<P extends object> {
  label: string;
  scope: string;
  exposedModule: string;
  url: string;
  componentProps: P;
  fallback?: React.ReactNode;
}

// Shared within shell only (not duplicated cross-app — this file never
// leaves shell's own build) — every lazy-loaded remote goes through this
// so the error-boundary + nonce-retry + Suspense wiring only has to be
// gotten right once.
export function RemoteSection<P extends object>({
  label,
  scope,
  exposedModule,
  url,
  componentProps,
  fallback,
}: RemoteSectionProps<P>) {
  const [nonce, setNonce] = React.useState(0);

  const RemoteComponent = React.useMemo(
    () =>
      React.lazy(() =>
        loadRemoteModule<{ default: React.ComponentType<P> }>(scope, exposedModule, url)
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scope, exposedModule, url, nonce]
  );

  // Cast to ComponentType<any> here — TS can't verify a generic P spreads
  // safely into a JSX element, but componentProps is typed P at every call
  // site, so this is sound.
  const Component = RemoteComponent as React.ComponentType<any>;

  return (
    <RemoteErrorBoundary label={label} onRetry={() => setNonce((n) => n + 1)}>
      <React.Suspense fallback={fallback ?? <div>Loading {label}…</div>}>
        <Component {...componentProps} />
      </React.Suspense>
    </RemoteErrorBoundary>
  );
}
