import { create } from "zustand";

export type ThemeChoice = "light" | "dark" | "system";
export const THEME_KEY = "edgebench.theme";

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" || v === "system" ? v : "system";
  } catch {
    return "system"; // storage can be blocked (private window); the app must still render
  }
}

function resolve(choice: ThemeChoice): "light" | "dark" {
  if (choice !== "system") return choice;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

interface ThemeState {
  choice: ThemeChoice;
  resolved: "light" | "dark";
  setChoice: (choice: ThemeChoice) => void;
  /** Forget the saved choice: back to following the system, with nothing stored. */
  reset: () => void;
}

function apply(choice: ThemeChoice): "light" | "dark" {
  const resolved = resolve(choice);
  document.documentElement.classList.toggle("dark", resolved === "dark");
  return resolved;
}

export const useTheme = create<ThemeState>((set) => {
  const choice = readChoice();
  return {
    choice,
    resolved: apply(choice),
    setChoice: (next) => {
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch {
        /* not persisted; still applies for this session */
      }
      set({ choice: next, resolved: apply(next) });
    },
    reset: () => {
      try {
        localStorage.removeItem(THEME_KEY);
      } catch {
        /* storage unavailable: nothing was saved to remove */
      }
      set({ choice: "system", resolved: apply("system") });
    },
  };
});

/** Follow the operating system while the choice is "system". Returns the cleanup function. */
export function watchSystemTheme(): () => void {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    const { choice } = useTheme.getState();
    if (choice === "system") useTheme.setState({ resolved: apply(choice) });
  };
  query.addEventListener("change", onChange);
  return () => {
    query.removeEventListener("change", onChange);
  };
}
