export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed";

export interface DocumentRecord {
  id: string;
  user_id: string;
  title: string;
  status: DocumentStatus;
  created_at: string;
}

export interface Chat {
  id: string;
  user_id: string;
  document_id: string;
  title: string | null;
  created_at: string;
}

export interface Message {
  id: string;
  chat_id: string;
  role: "user" | "assistant";
  content: string;
  quiz_id: string | null;
  created_at: string;
}

export interface Quiz {
  id: string;
  document_id: string;
  topic: string;
  questions: unknown;
  thread_id: string | null;
  created_at: string;
}

export interface QuizStats {
  avg_score: number | null;
  attempt_count: number;
}
