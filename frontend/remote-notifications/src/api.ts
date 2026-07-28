import { NotificationRecord } from "./types";

// The notifications service's own HTTP API — a different backend origin
// from core-api, called directly (not proxied through core-api).
const NOTIFICATIONS_URL = "http://localhost:5000";

export async function listNotifications(userId: string): Promise<NotificationRecord[]> {
  const res = await fetch(`${NOTIFICATIONS_URL}/notifications?user_id=${encodeURIComponent(userId)}`, {
    headers: { "X-User-Id": userId },
  });
  if (!res.ok) {
    throw new Error(`GET /notifications failed: ${res.status}`);
  }
  return res.json();
}
