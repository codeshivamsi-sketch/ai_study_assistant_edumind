import React from "react";
import { listNotifications } from "./api";
import { NotificationRecord } from "./types";

export interface Session {
  userId: string;
}

// Full list, fetched once — the persistent NotificationsWidget in shell's
// header is the only thing that polls; this route just reads a snapshot.
export function NotificationsPage({ session }: { session: Session }) {
  const [notifications, setNotifications] = React.useState<NotificationRecord[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    listNotifications(session.userId)
      .then(setNotifications)
      .catch((err) => setError(String(err)));
  }, [session.userId]);

  if (error) return <p>Failed to load notifications: {error}</p>;
  if (!notifications) return <p>Loading notifications…</p>;

  return (
    <div>
      <h2>Notifications</h2>
      {notifications.length === 0 && <p>No notifications yet.</p>}
      <ul>
        {notifications.map((n) => (
          <li key={n.id}>
            {n.message} — {new Date(n.created_at).toLocaleString()}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default NotificationsPage;
