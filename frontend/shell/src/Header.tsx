import React from "react";
import { Link } from "react-router-dom";
import { RemoteSection } from "./RemoteSection";
import { RemoteManifest } from "./utils/manifest";
import { Session } from "./SessionContext";

export function Header({ manifest, session }: { manifest: RemoteManifest; session: Session }) {
  return (
    <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 20px", borderBottom: "1px solid #d6d9e0" }}>
      <nav style={{ display: "flex", gap: 16 }}>
        <Link to="/chat">Chat</Link>
        <Link to="/notifications">Notifications</Link>
      </nav>
      {/* Always mounted, regardless of route — this is the persistent widget
          that polls for new notifications and fires the cross-remote event
          remote-chat listens for. */}
      <RemoteSection
        label="notifications bell"
        scope="notifications"
        exposedModule="./NotificationsWidget"
        url={manifest.notifications.url}
        componentProps={{ session }}
        fallback={<span>🔔</span>}
      />
    </header>
  );
}
