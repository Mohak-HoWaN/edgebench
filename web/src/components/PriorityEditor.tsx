import { ArrowDown, ArrowUp, X } from "lucide-react";
import { NativeSelect } from "@/components/Field";
import { Button } from "@/components/ui/button";
import { DEFAULT_PRIORITY, METRIC_BY_KEY, METRICS, usePriority } from "@/lib/metrics";

/** Choose which results matter to you and in what order: the first ranks the rows, all are shown in this order. */
export function PriorityEditor() {
  const order = usePriority((s) => s.order);
  const set = usePriority((s) => s.set);
  const reset = usePriority((s) => s.reset);
  const unused = METRICS.filter((m) => !order.includes(m.key));
  const move = (index: number, by: -1 | 1) => {
    const next = [...order];
    const [item] = next.splice(index, 1);
    if (item === undefined) return;
    next.splice(index + by, 0, item);
    set(next);
  };

  return (
    <div className="max-w-prose space-y-4">
      <ol className="divide-y border-y" aria-label="Your result priorities, most important first">
        {order.map((key, i) => {
          const m = METRIC_BY_KEY.get(key);
          if (!m) return null;
          return (
            <li key={key} className="flex items-center gap-2 py-2">
              <span className="w-6 text-sm tabular-nums text-muted-foreground">{i + 1}</span>
              <span className="flex-1 text-sm">
                <span className="font-medium">{m.label}</span>
                <span className="block text-xs text-muted-foreground">
                  {m.higher ? "higher is better" : "lower is better"}. {m.hint}
                </span>
              </span>
              <Button
                size="icon-sm"
                variant="ghost"
                disabled={i === 0}
                aria-label={`Move ${m.label} up`}
                onClick={() => {
                  move(i, -1);
                }}
              >
                <ArrowUp aria-hidden />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                disabled={i === order.length - 1}
                aria-label={`Move ${m.label} down`}
                onClick={() => {
                  move(i, 1);
                }}
              >
                <ArrowDown aria-hidden />
              </Button>
              <Button
                size="icon-sm"
                variant="ghost"
                disabled={order.length === 1}
                aria-label={`Remove ${m.label}`}
                onClick={() => {
                  set(order.filter((k) => k !== key));
                }}
              >
                <X aria-hidden />
              </Button>
            </li>
          );
        })}
      </ol>
      <div className="flex flex-wrap items-center gap-2">
        {unused.length > 0 ? (
          <>
            <label htmlFor="add-metric" className="text-sm">
              Add a metric
            </label>
            <NativeSelect
              id="add-metric"
              className="w-56"
              value=""
              onChange={(e) => {
                if (e.target.value) set([...order, e.target.value]);
              }}
            >
              <option value="">Choose...</option>
              {unused.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.label}
                </option>
              ))}
            </NativeSelect>
          </>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          disabled={order.join() === DEFAULT_PRIORITY.join()}
          onClick={reset}
        >
          Use the defaults
        </Button>
      </div>
    </div>
  );
}
