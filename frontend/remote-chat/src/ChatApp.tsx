import React from "react";
import { Routes, Route, Link } from "react-router-dom";
import { ChatList } from "./routes/ChatList";
import { ChatNew } from "./routes/ChatNew";
import { ChatDetail } from "./routes/ChatDetail";
import { QuizAnswer } from "./routes/QuizAnswer";
import { QuizStats } from "./routes/QuizStats";

export interface Session {
  userId: string;
}

// Renders only <Routes>/<Route> — never its own <BrowserRouter>. Shell
// mounts the single <BrowserRouter>; every remote's route tree lives
// under it, which is what lets navigate('/chat/:id') work regardless of
// which remote calls it.
export function ChatApp({ session }: { session: Session }) {
  return (
    <React.Suspense fallback={<div>Loading UI…</div>}>
      <div>
        <nav style={{ marginBottom: 16 }}>
          <Link to="/chat">All chats</Link>
        </nav>
        <Routes>
          <Route index element={<ChatList session={session} />} />
          <Route path="new" element={<ChatNew session={session} />} />
          <Route path=":chatId" element={<ChatDetail session={session} />} />
          <Route path=":chatId/quiz/:quizId/answer" element={<QuizAnswer session={session} />} />
          <Route path=":chatId/quiz/:quizId/stats" element={<QuizStats session={session} />} />
        </Routes>
      </div>
    </React.Suspense>
  );
}

export default ChatApp;
