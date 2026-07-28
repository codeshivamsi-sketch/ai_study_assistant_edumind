// Dev harness only — never exposed via Module Federation. Demo page proving
// the components render; other apps consume Button/TextInput/Card/theme via
// loadRemoteModule at runtime instead.
import React from "react";
import { createRoot } from "react-dom/client";
import { Button } from "./Button";
import { TextInput } from "./TextInput";
import { Card } from "./Card";
import { theme } from "./theme";

function DemoPage() {
  return (
    <div style={{ fontFamily: theme.font.family, padding: theme.spacing(6), display: "grid", gap: theme.spacing(4), maxWidth: 480 }}>
      <h1>design-system — dev harness</h1>
      <Card title="Buttons">
        <div style={{ display: "flex", gap: 8 }}>
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="danger">Danger</Button>
        </div>
      </Card>
      <Card title="Text input">
        <TextInput label="Document title" name="title" placeholder="e.g. Chapter 1 notes" />
      </Card>
    </div>
  );
}

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(<DemoPage />);
}
