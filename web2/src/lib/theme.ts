import { useEffect, useState } from "react";

/** Light, dark, or follow the system. Stored per browser; the page works without storage. */
export type Theme = "light" | "dark" | "system";

const KEY = "outbound.theme";

function read(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
}

/** Apply the stored theme before the first paint (called from main.tsx). */
export const applyStoredTheme = () => apply(read());

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    apply(theme);
    try {
      if (theme === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, theme);
    } catch {
      // Storage can be blocked (private windows); the choice then lasts for this visit only.
    }
  }, [theme]);
  return [theme, setTheme];
}
