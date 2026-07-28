// Dev harness only — never exposed via Module Federation. Wraps the exposed
// ChatApp in its own BrowserRouter + a hardcoded dev session — uses
// "alice", one of core-api's seeded test users.
import React from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ChatApp } from "./ChatApp";

const DEV_SESSION = { userId: "11111111-1111-1111-1111-111111111111" };

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(
    <BrowserRouter>
      <ChatApp session={DEV_SESSION} />
    </BrowserRouter>
  );
}
