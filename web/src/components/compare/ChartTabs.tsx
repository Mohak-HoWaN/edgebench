import { useRef, type KeyboardEvent, type ReactNode } from "react";

/** Charts grouped by the question they answer; the first ones in a tab are shown, the rest are folded under "More charts". */
export const TABS: { id: string; label: string; main: string[]; more: string[] }[] = [
  {
    id: "tradeoffs",
    label: "Which is the best trade-off?",
    main: ["scorecard", "accuracy-speed"],
    more: ["size-accuracy", "size-speed"],
  },
  {
    id: "speed",
    label: "Which is faster?",
    main: ["speed-up", "latency-distribution", "threads"],
    more: ["devices", "where-time-goes"],
  },
  {
    id: "accuracy",
    label: "Which is more accurate?",
    main: ["drift", "per-class"],
    more: ["pr-curve", "f1-curve", "score-distribution"],
  },
  {
    id: "mistakes",
    label: "Where does it go wrong?",
    main: ["confusion", "capture-source"],
    more: [],
  },
  {
    id: "machine",
    label: "Is the machine coping?",
    main: ["temperature"],
    more: ["latency-over-run"],
  },
];

export function ChartTabs({
  frames,
  tab,
  onTab,
}: {
  frames: Record<string, ReactNode>;
  tab: string;
  onTab: (tab: string) => void;
}) {
  const current = TABS.find((t) => t.id === tab) ?? TABS[0];
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  if (!current) return null;
  const move = (e: KeyboardEvent, i: number) => {
    const next =
      e.key === "ArrowRight"
        ? (i + 1) % TABS.length
        : e.key === "ArrowLeft"
          ? (i - 1 + TABS.length) % TABS.length
          : null;
    if (next === null) return;
    e.preventDefault();
    const target = TABS[next];
    if (target) {
      onTab(target.id);
      refs.current[next]?.focus();
    }
  };
  return (
    <section aria-label="Charts" className="mt-8">
      <h2 className="mb-2 text-lg font-semibold">Charts</h2>
      <div
        role="tablist"
        aria-label="What do you want to know?"
        className="sticky top-12 z-10 -mx-6 flex gap-1 overflow-x-auto border-b bg-background/95 px-6 backdrop-blur"
      >
        {TABS.map((t, i) => (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            type="button"
            id={`tab-${t.id}`}
            aria-selected={t.id === current.id}
            aria-controls={`panel-${t.id}`}
            tabIndex={t.id === current.id ? 0 : -1}
            onClick={() => {
              onTab(t.id);
            }}
            onKeyDown={(e) => {
              move(e, i);
            }}
            className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm ${t.id === current.id ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`panel-${current.id}`}
        aria-labelledby={`tab-${current.id}`}
        tabIndex={0}
        className="outline-none"
      >
        {current.main.map((id) => (
          <div key={id}>{frames[id]}</div>
        ))}
        {current.more.length > 0 ? (
          <details key={current.id} className="mt-4 border-t pt-4">
            <summary className="cursor-pointer text-sm font-medium">
              More charts for this question ({String(current.more.length)})
            </summary>
            {current.more.map((id) => (
              <div key={id}>{frames[id]}</div>
            ))}
          </details>
        ) : null}
      </div>
    </section>
  );
}
