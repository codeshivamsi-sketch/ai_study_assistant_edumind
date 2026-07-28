import { Chat, Message, Quiz, QuizStats, DocumentRecord } from "./types";

const CORE_API_URL = "http://localhost:8000";

async function request<T>(path: string, userId: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${CORE_API_URL}${path}`, {
    ...init,
    headers: { "X-User-Id": userId, ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function listChats(userId: string): Promise<Chat[]> {
  return request("/chats", userId);
}

export async function uploadDocument(userId: string, title: string, file: File): Promise<DocumentRecord> {
  const formData = new FormData();
  formData.append("title", title);
  formData.append("file", file);
  const res = await fetch(`${CORE_API_URL}/documents`, {
    method: "POST",
    headers: { "X-User-Id": userId },
    body: formData,
  });
  if (!res.ok) throw new Error(`upload failed: ${res.status}`);
  return res.json();
}

export function createOrGetChat(userId: string, documentId: string, title?: string): Promise<Chat> {
  return request("/chats", userId, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, title: title || undefined }),
  });
}

export function getChat(userId: string, chatId: string): Promise<Chat> {
  return request(`/chats/${chatId}`, userId);
}

export function listMessages(userId: string, chatId: string): Promise<Message[]> {
  return request(`/chats/${chatId}/messages`, userId);
}

export function sendMessage(
  userId: string,
  chatId: string,
  content: string,
  opts?: { intent?: string; quizId?: string }
): Promise<{ user_message: Message }> {
  return request(`/chats/${chatId}/messages`, userId, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      content,
      intent: opts?.intent,
      quiz_id: opts?.quizId,
    }),
  });
}

export function getQuiz(userId: string, quizId: string): Promise<Quiz> {
  return request(`/quizzes/${quizId}`, userId);
}

export function getQuizStats(userId: string, quizId: string): Promise<QuizStats> {
  return request(`/quizzes/${quizId}/stats`, userId);
}
