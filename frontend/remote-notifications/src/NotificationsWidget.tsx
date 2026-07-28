import React from "react";
import { listNotifications } from "./api";
import { NotificationRecord } from "./types";
import { dispatchNotificationEvent, EdumindNotificationDetail } from "./utils/eventBus";
import styles from "./NotificationsWidget.module.css";

export interface Session {
  userId: string;
}

const POLL_INTERVAL_MS = 10_000;

// chatId and quizId are independent — a notification always has a chat_id
// (an assistant message always gets created) and may additionally carry a
// quiz_id (quiz created, or a quiz answer graded). Neither field should be
// dropped in favor of the other.
function toEventDetail(n: NotificationRecord): EdumindNotificationDetail | null {
  if (!n.chat_id && !n.quiz_id) return null;
  return {
    chatId: n.chat_id ?? undefined,
    quizId: n.quiz_id ?? undefined,
    messageId: n.message_id ?? undefined,
  };
}

// Exposed remote widget: polls the notifications service directly (a
// different backend origin from core-api) and broadcasts a typed
// CustomEvent for anything new since the widget mounted — this is the
// dispatch side of the cross-remote event remote-chat subscribes to.
// Poll/fetch failures are shown inline, not thrown — a background polling
// hiccup shouldn't trip shell's error boundary for the whole section.
export function NotificationsWidget({ session }: { session: Session }) {
  const [notifications, setNotifications] = React.useState<NotificationRecord[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);
  const seenIds = React.useRef(new Set<string>());
  const firstPoll = React.useRef(true);

  React.useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await listNotifications(session.userId);
        if (cancelled) return;
        setNotifications(data);
        setError(null);

        if (firstPoll.current) {
          data.forEach((n) => seenIds.current.add(n.id));
          firstPoll.current = false;
        } else {
          for (const n of data) {
            if (!seenIds.current.has(n.id)) {
              seenIds.current.add(n.id);
              const detail = toEventDetail(n);
              if (detail) dispatchNotificationEvent(detail);
            }
          }
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    }

    poll();
    const intervalId = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(intervalId);
    };
  }, [session.userId]);

  const unreadCount = notifications.filter((n) => !n.read).length;

  return (
    <div className={styles.wrapper}>
      <button className={styles.bellButton} onClick={() => setOpen((o) => !o)} aria-label="Notifications">
        🔔
        {unreadCount > 0 && <span className={styles.badge}>{unreadCount}</span>}
      </button>
      {open && (
        <div className={styles.dropdown}>
          {error && <p className={styles.error}>{error}</p>}
          {!error && notifications.length === 0 && <p className={styles.empty}>No notifications yet.</p>}
          {notifications.map((n) => (
            <div key={n.id} className={styles.item}>
              {n.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default NotificationsWidget;
