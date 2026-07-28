// Manual dynamic-remote loader for webpack 5 native container.ModuleFederationPlugin.
// Duplicated verbatim per frontend/CONTRACTS.md — do not import across app folders.

type Container = {
  init(shareScope: unknown): Promise<void> | void;
  get(exposedModule: string): () => Promise<unknown>;
};

declare global {
  interface Window {
    [scope: string]: Container | undefined;
  }
  function __webpack_init_sharing__(scope: string): Promise<void>;
  // eslint-disable-next-line no-var
  var __webpack_share_scopes__: { default: unknown };
}

const loadedEntries = new Set<string>();

function loadScript(entryUrl: string): Promise<void> {
  if (loadedEntries.has(entryUrl)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = entryUrl;
    script.async = true;
    script.onload = () => {
      loadedEntries.add(entryUrl);
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed to load remoteEntry.js at ${entryUrl}`));
    document.head.appendChild(script);
  });
}

export async function loadRemoteModule<T = { default: unknown }>(
  scope: string,
  exposedModule: string,
  baseUrl: string
): Promise<T> {
  await loadScript(`${baseUrl.replace(/\/$/, "")}/remoteEntry.js`);
  const container = window[scope];
  if (!container) {
    throw new Error(`Remote container "${scope}" missing after loading ${baseUrl}`);
  }
  await __webpack_init_sharing__("default");
  await container.init(__webpack_share_scopes__.default);
  const factory = await container.get(exposedModule);
  return factory() as T;
}
