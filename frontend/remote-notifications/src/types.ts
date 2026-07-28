export interface NotificationRecord {
  id: string;
  user_id: string;
  quiz_id: string | null;
  chat_id: string | null;
  message_id: string | null;
  message: string;
  read: boolean;
  created_at: string;
}
