import React from "react";
import styles from "./TextInput.module.css";

export interface TextInputProps
  extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export function TextInput({ label, id, className, ...rest }: TextInputProps) {
  const inputId = id ?? rest.name;
  return (
    <div className={styles.field}>
      {label && (
        <label className={styles.label} htmlFor={inputId}>
          {label}
        </label>
      )}
      <input id={inputId} className={[styles.input, className].filter(Boolean).join(" ")} {...rest} />
    </div>
  );
}

export default TextInput;
