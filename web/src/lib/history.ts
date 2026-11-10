import { type createBrowserRouter, NavigationType } from "react-router-dom";
import { create } from "zustand";

/** React Router numbers every history entry; that number is where we are. */
function position(): number {
  const state = window.history.state as { idx?: number } | null;
  return typeof state?.idx === "number" ? state.idx : 0;
}

/** Where we are in the pages visited, and how far forward goes (only after going back). */
export const useHistoryPosition = create<{ here: number; furthest: number }>(() => ({
  here: position(),
  furthest: position(),
}));

/** Feed the store from the router. Opening a new page cuts off whatever was ahead; going back or forward keeps it. */
export function trackHistory(router: ReturnType<typeof createBrowserRouter>): void {
  router.subscribe((state) => {
    const here = position();
    useHistoryPosition.setState((s) => ({
      here,
      furthest: state.historyAction === NavigationType.Pop ? Math.max(s.furthest, here) : here,
    }));
  });
}
