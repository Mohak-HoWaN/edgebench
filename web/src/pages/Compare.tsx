import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CompareCharts } from "@/components/compare/CompareCharts";
import { RunTable, Suggestions } from "@/components/compare/RunPicker";
import { SpecTable } from "@/components/compare/SpecTable";
import { toLimits, VerdictCard, type LimitText } from "@/components/compare/VerdictCard";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { mapOf } from "@/lib/compare/builders";
import {
  cannotAdd,
  MAX_MODELS,
  MAX_RUNS,
  notesFor,
  subjectsOf,
  suggestions,
} from "@/lib/compare/subjects";
import { verdict as decide } from "@/lib/compare/verdict";
import { useDriftLimits } from "@/lib/drift";
import { priorityMetrics, usePriority } from "@/lib/metrics";
import { useModels } from "@/lib/models";
import { useRuns, type RunInfo } from "@/lib/runs";

/**
 * Compare any runs: different models, variants, thread counts, datasets or devices, up to 12 runs and 3 models at once. The answer
 * comes first (which run to pick, given your limits), then the facts side by side, then the charts, grouped by the question each
 * answers. Everything chosen lives in the address (`?runs=3,7,9&ref=3&tab=speed&maxms=40`), so a comparison can be shared or reopened.
 * With no choice made the page starts from the first ready-made comparison.
 */
export default function Compare() {
  const runs = useRuns();
  const models = useModels();
  const order = usePriority((s) => s.order);
  const band = useDriftLimits((s) => s.maxMapDropPoints);
  const [params, setParams] = useSearchParams();
  const metrics = useMemo(() => priorityMetrics(order), [order]);

  const live = useMemo(() => {
    const ids = new Set((models.data ?? []).map((m) => m.id));
    return (runs.data ?? []).filter(
      (r) => r.status === "done" && r.model_id !== null && ids.has(r.model_id),
    );
  }, [runs.data, models.data]);
  const ready = useMemo(() => suggestions(live.filter((r) => r.diagnosis.length === 0)), [live]);

  const raw = params.get("runs");
  const ids = useMemo(
    () =>
      raw === null
        ? (ready[0]?.runIds ?? [])
        : raw.split(",").filter(Boolean).map(Number).filter(Number.isFinite),
    [raw, ready],
  );
  const subjects = useMemo(() => subjectsOf(live, ids), [live, ids]);
  const refId = Number(params.get("ref"));
  const reference = subjects.find((s) => s.run.id === refId) ?? subjects[0];

  // Limits: what is in the address, else (for accuracy) the reference's score less the drop allowed in Settings.
  const refAccuracy = reference ? mapOf(reference.run) : undefined;
  const defaults: LimitText = {
    acc: refAccuracy === undefined ? "" : (refAccuracy * 100 - band).toFixed(1),
    ms: "",
    mb: "",
  };
  const limitText: LimitText = {
    acc: params.get("minacc") ?? defaults.acc,
    ms: params.get("maxms") ?? "",
    mb: params.get("maxmb") ?? "",
  };
  const limits = useMemo(() => toLimits(limitText), [limitText.acc, limitText.ms, limitText.mb]); // eslint-disable-line react-hooks/exhaustive-deps
  const answer = useMemo(() => decide(subjects, limits, metrics), [subjects, limits, metrics]);

  const set = (change: (p: URLSearchParams) => void) => {
    setParams(
      (p) => {
        change(p);
        return p;
      },
      { replace: true },
    );
  };
  const write = (next: number[], ref?: number) => {
    set((p) => {
      p.set("runs", next.join(","));
      if (ref !== undefined) p.set("ref", String(ref));
    });
  };
  const toggle = (run: RunInfo) => {
    if (cannotAdd(subjects, run) !== null) return;
    const have = subjects.map((s) => s.run.id);
    write(have.includes(run.id) ? have.filter((x) => x !== run.id) : [...have, run.id]);
  };
  const notes = notesFor(subjects);

  return (
    <>
      <PageHeader
        title="Compare"
        hint="Put any runs side by side: two models on the same variant, one model's variants, a thread sweep, the same run on two machines. You get the answer first, then every fact side by side, then charts grouped by the question each one answers."
      />
      {runs.isPending || models.isPending ? (
        <Skeleton aria-busy="true" aria-label="Loading runs" className="h-24 max-w-prose" />
      ) : runs.isError ? (
        <p className="text-sm">The runs could not be loaded: {runs.error.message}</p>
      ) : live.length === 0 ? (
        <EmptyState
          title="Nothing to compare yet"
          action={{ label: "Plan an experiment", to: "/experiments/new" }}
        >
          Finished runs of models that still exist are compared here. Run an experiment first.
        </EmptyState>
      ) : (
        <>
          <section aria-labelledby="pick-heading">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <h2 id="pick-heading" className="text-lg font-semibold">
                What to compare
              </h2>
              <span aria-live="polite">
                {String(subjects.length)} of {String(MAX_RUNS)} runs,{" "}
                {String(new Set(subjects.map((s) => s.run.model_id)).size)} of {String(MAX_MODELS)}{" "}
                models
              </span>
              {subjects.length > 0 ? (
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => {
                    write([]);
                  }}
                >
                  Clear all
                </Button>
              ) : null}
            </div>
            {subjects.length === 0 ? (
              <p className="mt-2 max-w-prose text-sm text-muted-foreground">
                Nothing is selected. Pick a ready-made comparison, or choose runs from the list.
              </p>
            ) : null}
            {notes.length > 0 ? (
              <ul
                className="mt-3 max-w-prose list-disc space-y-1 border-l-2 border-warn pl-6 text-sm"
                aria-label="What differs between these runs"
              >
                {notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            ) : null}
            <details className="mt-3" open={subjects.length === 0}>
              <summary className="cursor-pointer text-sm font-medium">
                Ready-made comparisons
              </summary>
              <div className="mt-3">
                <Suggestions
                  items={ready}
                  onPick={(picked) => {
                    write(picked, picked[0]);
                  }}
                />
              </div>
            </details>
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-medium">Choose runs yourself</summary>
              <div className="mt-3">
                <RunTable runs={live} selected={subjects} onToggle={toggle} />
              </div>
            </details>
          </section>

          {subjects.length === 0 ? null : (
            <>
              <div className="mt-6">
                <VerdictCard
                  verdict={answer}
                  limits={limitText}
                  defaults={defaults}
                  onLimits={(next) => {
                    set((p) => {
                      p.set("minacc", next.acc);
                      p.set("maxms", next.ms);
                      p.set("maxmb", next.mb);
                    });
                  }}
                />
              </div>
              <SpecTable
                subjects={subjects}
                reference={reference}
                verdict={answer}
                onRemove={(id) => {
                  write(subjects.map((s) => s.run.id).filter((x) => x !== id));
                }}
                onReference={(id) => {
                  write(
                    subjects.map((s) => s.run.id),
                    id,
                  );
                }}
              />
              <CompareCharts
                subjects={subjects}
                reference={reference}
                metrics={metrics}
                band={band}
                limits={limits}
                tab={params.get("tab") ?? "tradeoffs"}
                onTab={(tab) => {
                  set((p) => {
                    p.set("tab", tab);
                  });
                }}
              />
              <p className="mt-6 max-w-prose text-xs text-muted-foreground">
                Metrics, their order and the allowed accuracy drop come from{" "}
                <Link to="/settings" className="text-primary underline underline-offset-4">
                  Settings
                </Link>
                .
              </p>
            </>
          )}
        </>
      )}
    </>
  );
}
