import React from "react";
import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "secondary" | "danger";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

export function Button({ variant = "primary", className, ...rest }: ButtonProps) {
  const variantClass = variant !== "primary" ? styles[variant] : undefined;
  const classes = [styles.button, variantClass, className].filter(Boolean).join(" ");
  return <button className={classes} {...rest} />;
}

export default Button;
