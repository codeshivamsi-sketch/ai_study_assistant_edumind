export const theme = {
  color: {
    background: "#ffffff",
    surface: "#f4f5f7",
    border: "#d6d9e0",
    text: "#1a1d23",
    textMuted: "#5c6270",
    primary: "#3457d5",
    primaryText: "#ffffff",
    danger: "#c0392b",
  },
  radius: "6px",
  spacing: (n: number) => `${n * 4}px`,
  font: {
    family:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
};

export type Theme = typeof theme;
