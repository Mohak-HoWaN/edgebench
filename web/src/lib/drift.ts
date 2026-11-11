import { create } from "zustand";

/**
 * How far a converted variant may drift from the PyTorch baseline before the accuracy check says it fails. Kept in this browser
 * like the metric priorities; the server applies the limits it is sent, so there is one implementation of the verdict.
 */
export interface DriftLimits {
  /** mAP50 may fall by this many points (percentage points of the 0-100 scale). */
  maxMapDropPoints: number;
  /** Mean agreement between the variant's boxes and the baseline's, 0 to 1. */
  minAgreement: number;
}

export const DEFAULT_LIMITS: DriftLimits = { maxMapDropPoints: 5, minAgreement: 0.8 };
export const LIMITS_KEY = "edgebench.drift-limits";

function read(): DriftLimits {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(LIMITS_KEY) ?? "null");
    if (typeof raw === "object" && raw !== null) {
      const { maxMapDropPoints: drop, minAgreement: agree } = raw as Partial<DriftLimits>;
      if (
        typeof drop === "number" &&
        typeof agree === "number" &&
        drop >= 0 &&
        drop <= 100 &&
        agree >= 0 &&
        agree <= 1
      )
        return { maxMapDropPoints: drop, minAgreement: agree };
    }
  } catch {
    /* unreadable or blocked storage: use the defaults */
  }
  return DEFAULT_LIMITS;
}

interface LimitsState extends DriftLimits {
  set: (limits: DriftLimits) => void;
  reset: () => void;
}

export const useDriftLimits = create<LimitsState>((set) => ({
  ...read(),
  set: (limits) => {
    try {
      localStorage.setItem(LIMITS_KEY, JSON.stringify(limits));
    } catch {
      /* not persisted; still applies for this session */
    }
    set(limits);
  },
  reset: () => {
    try {
      localStorage.removeItem(LIMITS_KEY);
    } catch {
      /* nothing was saved to remove */
    }
    set(DEFAULT_LIMITS);
  },
}));

/** The query string that carries the limits to the server, which decides pass or fail. */
export const limitsQuery = (l: DriftLimits) =>
  `max_map_drop=${String(l.maxMapDropPoints / 100)}&min_agreement=${String(l.minAgreement)}`;
