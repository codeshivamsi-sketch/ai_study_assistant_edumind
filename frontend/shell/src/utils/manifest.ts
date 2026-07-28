// Duplicated per frontend/CONTRACTS.md. Fetches the runtime remote manifest —
// never bundled at build time, so pinning/rolling back one remote is a file
// edit + refresh, not a rebuild. See frontend/manifest/remotes.json (canonical,
// Docker) vs this app's own public/remotes.json (dev-only).

export interface RemoteEntry {
  url: string;
  version: string;
}

export interface RemoteManifest {
  designSystem: RemoteEntry;
  documents: RemoteEntry;
  chat: RemoteEntry;
  notifications: RemoteEntry;
}

let manifestPromise: Promise<RemoteManifest> | null = null;

export function fetchManifest(): Promise<RemoteManifest> {
  if (!manifestPromise) {
    manifestPromise = fetch("/remotes.json").then((res) => {
      if (!res.ok) throw new Error(`Failed to fetch remotes.json: ${res.status}`);
      return res.json() as Promise<RemoteManifest>;
    });
  }
  return manifestPromise;
}
