import React from "react";
import { Link } from "react-router-dom";
import { listChats } from "../api";
import { Chat } from "../types";
import { Card } from "../remoteUi";
import styles from "./ChatList.module.css";

export function ChatList({ session }: { session: { userId: string } }) {
  const [chats, setChats] = React.useState<Chat[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    listChats(session.userId)
      .then(setChats)
      .catch((err) => setError(String(err)));
  }, [session.userId]);

  if (error) return <p>Failed to load chats: {error}</p>;
  if (!chats) return <p>Loading chats…</p>;

  return (
    <div className={styles.list}>
      <div className={styles.header}>
        <h2>Chats</h2>
        <Link to="/chat/new">+ New chat</Link>
      </div>
      {chats.length === 0 && <p>No chats yet — start one to upload a document and begin.</p>}
      <div className={styles.grid}>
        {chats.map((chat) => (
          <Card key={chat.id} title={chat.title || "Untitled chat"}>
            <Link to={`/chat/${chat.id}`}>Open</Link>
          </Card>
        ))}
      </div>
    </div>
  );
}
