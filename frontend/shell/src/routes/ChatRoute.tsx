import React from "react";
import { RemoteSection } from "../RemoteSection";
import { RemoteManifest } from "../utils/manifest";
import { Session } from "../SessionContext";

export function ChatRoute({ manifest, session }: { manifest: RemoteManifest; session: Session }) {
  return (
    <RemoteSection
      label="chat"
      scope="chat"
      exposedModule="./ChatApp"
      url={manifest.chat.url}
      componentProps={{ session }}
    />
  );
}
