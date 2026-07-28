import React from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { getQuiz, sendMessage } from "../api";
import { Quiz } from "../types";
import { Button, Card, TextInput } from "../remoteUi";
import styles from "./QuizAnswer.module.css";

export function QuizAnswer({ session }: { session: { userId: string } }) {
  const { chatId, quizId } = useParams<{ chatId: string; quizId: string }>();
  const navigate = useNavigate();
  const [quiz, setQuiz] = React.useState<Quiz | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [answer, setAnswer] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);

  React.useEffect(() => {
    if (!quizId) return;
    getQuiz(session.userId, quizId)
      .then(setQuiz)
      .catch((err) => setError(String(err)));
  }, [session.userId, quizId]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!chatId || !quizId || !answer.trim()) return;
    setSubmitting(true);
    try {
      await sendMessage(session.userId, chatId, answer.trim(), { intent: "quiz_answer", quizId });
      navigate(`/chat/${chatId}`);
    } catch (err) {
      setError(String(err));
      setSubmitting(false);
    }
  }

  if (error) return <p>Failed to load quiz: {error}</p>;
  if (!quiz) return <p>Loading quiz…</p>;

  return (
    <div className={styles.answer}>
      <Link to={`/chat/${chatId}`}>&larr; Back to chat</Link>
      <Card title={quiz.topic}>
        <pre className={styles.questions}>{JSON.stringify(quiz.questions, null, 2)}</pre>
      </Card>
      <form onSubmit={handleSubmit} className={styles.form}>
        <TextInput
          label="Your answer"
          value={answer}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setAnswer(e.target.value)}
        />
        <Button type="submit" disabled={submitting}>
          {submitting ? "Submitting…" : "Submit for grading"}
        </Button>
      </form>
      <p className={styles.note}>
        Grading happens asynchronously — the score and feedback show up as a chat message once ready.
      </p>
    </div>
  );
}
