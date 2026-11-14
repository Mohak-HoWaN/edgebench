import { create } from "zustand";
import { DEFAULT_VIEW, type View } from "./explorer.ts";

export const VIEWS_KEY = "edgebench.saved-views";

export interface SavedView {
  name: string;
  view: View;
}

function read(): SavedView[] {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(VIEWS_KEY) ?? "[]");
    if (Array.isArray(raw))
      return raw.flatMap((x: unknown) => {
        const v = x as { name?: unknown; view?: unknown } | null;
        return v && typeof v.name === "string" && typeof v.view === "object" && v.view !== null
          ? [{ name: v.name, view: { ...DEFAULT_VIEW, ...(v.view as Partial<View>) } }]
          : [];
      });
  } catch {
    /* unreadable or blocked storage: no saved views */
  }
  return [];
}

function write(views: SavedView[]) {
  try {
    localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
  } catch {
    /* not persisted; still applies for this session */
  }
}

interface ViewsState {
  views: SavedView[];
  /** Saving under a name that exists replaces that view. */
  save: (name: string, view: View) => void;
  remove: (name: string) => void;
}

/** Filter, sort and grouping choices of the all-runs table that a person wants back later; kept in this browser. */
export const useViews = create<ViewsState>((set, get) => ({
  views: read(),
  save: (name, view) => {
    const next = [...get().views.filter((v) => v.name !== name), { name, view }];
    write(next);
    set({ views: next });
  },
  remove: (name) => {
    const next = get().views.filter((v) => v.name !== name);
    write(next);
    set({ views: next });
  },
}));
