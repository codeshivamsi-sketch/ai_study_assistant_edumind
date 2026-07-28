import React from "react";
import { useParams, Link } from "react-router-dom";
import { getQuizStats } from "../api";
import { QuizStats as QuizStatsType } from "../types";
import { Card } from "../remoteUi";
import styles from "./QuizStats.module.css";

export function QuizStats({ session }: { session: { userId: string } }) {
  const { chatId, quizId } = useParams<{ chatId: string; quizId: string }>();
  const [stats, setStats] = React.useState<QuizStatsType | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!quizId) return;
    getQuizStats(session.userId, quizId)
      .then(setStats)
      .catch((err) => setError(String(err)));
  }, [session.userId, quizId]);

  if (error) return <p>Failed to load stats: {error}</p>;
  if (!stats) return <p>Loading stats…</p>;

  return (
    <div className={styles.stats}>
      <Link to={`/chat/${chatId}`}>&larr; Back to chat</Link>
      <Card title="Quiz stats">
        <p>Attempts: {stats.attempt_count}</p>
        <p>Average score: {stats.avg_score ?? "—"}</p>
      </Card>
    </div>
  );
}
