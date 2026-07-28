import React from "react";
import { useNavigate } from "react-router-dom";
import { uploadDocument, createOrGetChat } from "../api";
import { Button, TextInput } from "../remoteUi";
import styles from "./ChatNew.module.css";

export function ChatNew({ session }: { session: { userId: string } }) {
  const navigate = useNavigate();
  const [title, setTitle] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [status, setStatus] = React.useState<"idle" | "uploading" | "error">("idle");
  const [error, setError] = React.useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !file) return;
    setStatus("uploading");
    setError(null);
    try {
      const document = await uploadDocument(session.userId, title.trim(), file);
      const chat = await createOrGetChat(session.userId, document.id, document.title);
      navigate(`/chat/${chat.id}`);
    } catch (err) {
      setStatus("error");
      setError(String(err));
    }
  }

  return (
    <form onSubmit={handleSubmit} className={styles.form}>
      <h2>New chat</h2>
      <p>Upload a document to start a chat about it.</p>
      <TextInput
        label="Title"
        value={title}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)}
        required
      />
      <label className={styles.fileLabel}>
        File
        <input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
      </label>
      <Button type="submit" disabled={status === "uploading"}>
        {status === "uploading" ? "Uploading…" : "Upload & start chat"}
      </Button>
      {status === "error" && <p className={styles.error}>{error}</p>}
    </form>
  );
}
