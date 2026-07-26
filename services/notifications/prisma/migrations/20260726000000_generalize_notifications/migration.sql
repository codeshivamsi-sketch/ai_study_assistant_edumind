-- AlterTable: quiz_id becomes optional (chat-answer notifications have none)
ALTER TABLE "notifications" ALTER COLUMN "quiz_id" DROP NOT NULL;

-- AlterTable: new optional columns for chat-answer notifications
ALTER TABLE "notifications" ADD COLUMN "chat_id" UUID;
ALTER TABLE "notifications" ADD COLUMN "message_id" UUID;

-- AddForeignKey (hand-written, same pattern as the existing user_id FK —
-- chats/messages are core-api's Alembic tables, not Prisma's)
ALTER TABLE "notifications" ADD CONSTRAINT "notifications_chat_id_fkey" FOREIGN KEY ("chat_id") REFERENCES "chats"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "notifications" ADD CONSTRAINT "notifications_message_id_fkey" FOREIGN KEY ("message_id") REFERENCES "messages"("id") ON DELETE CASCADE ON UPDATE CASCADE;
