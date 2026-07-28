// Typed wrapper around the `edumind:notification` CustomEvent. Duplicated per
// frontend/CONTRACTS.md — remote-chat is the subscribe side, remote-notifications
// is the dispatch side.
//
// A notification always belongs to a chat (chat_id is always set on the
// backend's assistant-message callback) and may *additionally* carry a
// quiz_id (quiz created, or a quiz answer graded) — chatId/quizId are
// independent optional fields, not a mutually-exclusive discriminated union.
// A prior version picked one-or-the-other by priority, which silently
// dropped the chat refresh signal whenever a quizId was also present (quiz
// creation and quiz-answer evaluation never notified remote-chat).

export interface EdumindNotificationDetail {
  chatId?: string;
  quizId?: string;
  messageId?: string;
}

const EVENT_NAME = "edumind:notification";

export function dispatchNotificationEvent(detail: EdumindNotificationDetail): void {
  window.dispatchEvent(new CustomEvent<EdumindNotificationDetail>(EVENT_NAME, { detail }));
}

export function subscribeToNotificationEvent(
  handler: (detail: EdumindNotificationDetail) => void
): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<EdumindNotificationDetail>).detail);
  window.addEventListener(EVENT_NAME, listener);
  return () => window.removeEventListener(EVENT_NAME, listener);
}
