import React from "react";
import styles from "./Card.module.css";

export interface CardProps {
  title?: string;
  children?: React.ReactNode;
  className?: string;
}

export function Card({ title, children, className }: CardProps) {
  return (
    <div className={[styles.card, className].filter(Boolean).join(" ")}>
      {title && <h3 className={styles.title}>{title}</h3>}
      {children}
    </div>
  );
}

export default Card;
