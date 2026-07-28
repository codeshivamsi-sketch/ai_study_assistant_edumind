// Dev harness only — never exposed via Module Federation. Renders both
// exposed components against a hardcoded dev session — uses "alice", one
// of core-api's seeded test users.
import React from "react";
import { createRoot } from "react-dom/client";
import { NotificationsWidget } from "./NotificationsWidget";
import { NotificationsPage } from "./NotificationsPage";

const DEV_SESSION = { userId: "11111111-1111-1111-1111-111111111111" };

function DevHarness() {
  return (
    <div style={{ padding: 24 }}>
      <h1>remote-notifications — dev harness</h1>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 24 }}>
        <NotificationsWidget session={DEV_SESSION} />
      </div>
      <NotificationsPage session={DEV_SESSION} />
    </div>
  );
}

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(<DevHarness />);
}
