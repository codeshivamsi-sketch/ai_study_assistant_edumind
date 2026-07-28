// Lazily pulls Button/Card/TextInput from the design-system remote at
// runtime.
import React from "react";
import { loadRemoteModule } from "./utils/loadRemoteModule";
import { fetchManifest } from "./utils/manifest";

type AnyComponent = React.ComponentType<any>;

export const Button: AnyComponent = React.lazy(() =>
  fetchManifest().then((m) => loadRemoteModule<{ default: AnyComponent }>("designSystem", "./Button", m.designSystem.url))
);

export const Card: AnyComponent = React.lazy(() =>
  fetchManifest().then((m) => loadRemoteModule<{ default: AnyComponent }>("designSystem", "./Card", m.designSystem.url))
);

export const TextInput: AnyComponent = React.lazy(() =>
  fetchManifest().then((m) => loadRemoteModule<{ default: AnyComponent }>("designSystem", "./TextInput", m.designSystem.url))
);
