import React from "react";
import { useParams, Link } from "react-router-dom";
import { getChat, listMessages, sendMessage } from "../api";
import { Chat, Message } from "../types";
import { subscribeToNotificationEvent } from "../utils/eventBus";
import { Button, Card, TextInput } from "../remoteUi";
import styles from "./ChatDetail.module.css";

export function ChatDetail({ session }: { session: { userId: string } }) {
  const { chatId } = useParams<{ chatId: string }>();
  const [chat, setChat] = React.useState<Chat | null>(null);
  const [messages, setMessages] = React.useState<Message[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const [sending, setSending] = React.useState(false);
  const [awaitingReply, setAwaitingReply] = React.useState(false);
  const [sendError, setSendError] = React.useState<string | null>(null);

  const refreshMessages = React.useCallback(() => {
    if (!chatId) return;
    listMessages(session.userId, chatId)
      .then(setMessages)
      .catch((err) => setError(String(err)));
  }, [session.userId, chatId]);

  React.useEffect(() => {
    if (!chatId) return;
    let cancelled = false;

    getChat(session.userId, chatId)
      .then((c) => {
        if (!cancelled) setChat(c);
      })
      .catch((err) => setError(String(err)));
    refreshMessages();

    return () => {
      cancelled = true;
    };
  }, [chatId, session.userId, refreshMessages]);

  // No polling here — the notifications remote is the only thing that polls
  // (its bell widget, every 10s). This route just refetches messages when it
  // broadcasts that this exact chat has a new answer. Event cleanup is
  // required so a stale subscription doesn't outlive the route.
  React.useEffect(() => {
    const unsubscribe = subscribeToNotificationEvent((detail) => {
      if (detail.chatId === chatId) {
        refreshMessages();
        setAwaitingReply(false);
      }
    });
    return unsubscribe;
  }, [chatId, refreshMessages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!chatId || !draft.trim()) return;
    setSending(true);
    setSendError(null);
    try {
      await sendMessage(session.userId, chatId, draft.trim());
      setDraft("");
      setAwaitingReply(true);
      refreshMessages();
    } catch (err) {
      setSendError(String(err));
    } finally {
      setSending(false);
    }
  }

  if (error) return <p>Failed to load chat: {error}</p>;
  if (!chat) return <p>Loading chat…</p>;

  return (
    <div className={styles.detail}>
      <Link to="/chat">&larr; Back to chats</Link>
      <h2>{chat.title || "Untitled chat"}</h2>

      <div className={styles.messages}>
        {messages.length === 0 && <p>No messages yet — ask a question below.</p>}
        {messages.map((m) => (
          <Card key={m.id} className={m.role === "assistant" ? styles.assistant : styles.user}>
            <p className={styles.role}>{m.role}</p>
            <p>{m.content}</p>
            {m.quiz_id && (
              <p className={styles.quizActions}>
                <Link to={`/chat/${chatId}/quiz/${m.quiz_id}/answer`}>Answer</Link>{" "}
                <Link to={`/chat/${chatId}/quiz/${m.quiz_id}/stats`}>Stats</Link>
              </p>
            )}
          </Card>
        ))}
      </div>

      <form onSubmit={handleSend} className={styles.composeForm}>
        <TextInput
          label="Ask a question, or say 'quiz me' / 'summarize this'"
          value={draft}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setDraft(e.target.value)}
          disabled={sending || awaitingReply}
        />
        <Button type="submit" disabled={sending || awaitingReply}>
          {sending ? "Sending…" : awaitingReply ? "Processing…" : "Send"}
        </Button>
      </form>
      {awaitingReply && <p className={styles.pending}>Please wait, processing…</p>}
      {sendError && <p className={styles.error}>Failed to send: {sendError}</p>}
    </div>
  );
}
