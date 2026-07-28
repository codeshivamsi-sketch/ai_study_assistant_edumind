import React from "react";
import { RemoteSection } from "../RemoteSection";
import { RemoteManifest } from "../utils/manifest";
import { Session } from "../SessionContext";

export function NotificationsRoute({ manifest, session }: { manifest: RemoteManifest; session: Session }) {
  return (
    <RemoteSection
      label="notifications"
      scope="notifications"
      exposedModule="./NotificationsPage"
      url={manifest.notifications.url}
      componentProps={{ session }}
    />
  );
}
