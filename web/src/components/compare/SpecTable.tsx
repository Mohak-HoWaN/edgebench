import { Check, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Info } from "@/components/Info";
import { Mark } from "@/components/charts/kit";
import { specSheet, type Group } from "@/lib/compare/spec";
import type { Subject } from "@/lib/compare/subjects";
import type { Verdict } from "@/lib/compare/verdict";

/**
 * The spec sheet: one column per run, rows grouped (Accuracy, Speed, Size and set-up, The machine), the best of each row marked with
 * a tick and the word "best", run names that stay put while you scroll, and a switch that hides the rows where every run is the
 * same (the pattern Baymard's tests found people read fastest).
 */
export function SpecTable({
  subjects,
  reference,
  verdict,
  onRemove,
  onReference,
}: {
  subjects: Subject[];
  reference: Subject | undefined;
  verdict: Verdict;
  onRemove: (id: number) => void;
  onReference: (id: number) => void;
}) {
  const [onlyDiff, setOnlyDiff] = useState(true);
  const all = useMemo(() => specSheet(subjects), [subjects]);
  const rows = onlyDiff ? all.filter((r) => !r.same) : all;
  const hidden = all.length - rows.length;
  const winnerId = verdict.winner?.run.id;
  const failed = new Map(verdict.failed.map((f) => [f.subject.run.id, f.reasons.join("; ")]));
  const groups = [...new Set(rows.map((r) => r.group))] as Group[];
  if (subjects.length === 0) return null;
  return (
    <section aria-labelledby="spec-heading" className="mt-8">
      <div className="mb-2 flex flex-wrap items-center gap-4">
        <h2 id="spec-heading" className="text-lg font-semibold">
          Side by side
        </h2>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onlyDiff}
            onChange={(e) => {
              setOnlyDiff(e.target.checked);
            }}
          />
          Only show differences
          {onlyDiff && hidden > 0 ? (
            <span className="text-muted-foreground">
              ({String(hidden)} rows that are the same are hidden)
            </span>
          ) : null}
        </label>
      </div>
      <div className="max-h-[70vh] max-w-full overflow-auto rounded-lg border">
        <table className="w-full min-w-max text-sm">
          <thead className="sticky top-0 z-10 bg-background">
            <tr className="border-b">
              <th
                scope="col"
                className="sticky left-0 z-10 min-w-48 bg-background px-3 py-2 text-left font-medium text-muted-foreground"
              >
                <span className="sr-only">Fact</span>
              </th>
              {subjects.map((s) => (
                <th
                  key={s.run.id}
                  scope="col"
                  className={`min-w-40 px-3 py-2 text-left align-top font-normal `}
                >
                  <span className="flex items-start gap-1.5">
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 16 16"
                      aria-hidden
                      className="mt-0.5 shrink-0"
                    >
                      <Mark subject={s} x={8} y={8} r={5} />
                    </svg>
                    <span>
                      <Link
                        to={`/results/${String(s.run.id)}`}
                        className="font-medium text-primary underline-offset-4 hover:underline"
                      >
                        {s.modelName}
                      </Link>
                      <span className="block text-xs text-muted-foreground">
                        {s.run.variant_label}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {s.label.split(" · ")[1]}
                      </span>
                      {s.run.id === winnerId ? (
                        <span className="mt-1 inline-flex items-center gap-1 rounded bg-primary px-1.5 py-0.5 text-xs font-medium text-primary-foreground">
                          Best pick
                        </span>
                      ) : null}
                      {failed.has(s.run.id) ? (
                        <span className="mt-1 block text-xs text-warn">Misses a limit</span>
                      ) : null}
                      <span className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                        <label className="flex items-center gap-1">
                          <input
                            type="radio"
                            name="reference-col"
                            checked={reference?.run.id === s.run.id}
                            onChange={() => {
                              onReference(s.run.id);
                            }}
                          />
                          Reference<span className="sr-only"> {s.long}</span>
                        </label>
                        <button
                          type="button"
                          className="rounded p-0.5 hover:text-foreground"
                          onClick={() => {
                            onRemove(s.run.id);
                          }}
                        >
                          <X aria-hidden className="size-3.5" />
                          <span className="sr-only">Remove {s.long}</span>
                        </button>
                      </span>
                    </span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td
                  colSpan={subjects.length + 1}
                  className="px-3 py-6 text-center text-muted-foreground"
                >
                  These runs are the same in every fact listed. Switch off &ldquo;Only show
                  differences&rdquo; to see them.
                </td>
              </tr>
            ) : null}
            {groups.map((g) => (
              <GroupRows
                key={g}
                group={g}
                rows={rows.filter((r) => r.group === g)}
                subjects={subjects}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function GroupRows({
  group,
  rows,
  subjects,
}: {
  group: Group;
  rows: ReturnType<typeof specSheet>;
  subjects: Subject[];
}) {
  return (
    <>
      <tr>
        <th
          scope="colgroup"
          colSpan={subjects.length + 1}
          className="sticky left-0 bg-muted px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground"
        >
          {group}
        </th>
      </tr>
      {rows.map((r) => (
        <tr key={r.key} className="border-b">
          <th scope="row" className="sticky left-0 bg-background px-3 py-2 text-left font-normal">
            <span className="flex items-center gap-1.5">
              {r.label}
              {r.hint ? <Info>{`${r.tech ? `${r.tech}. ` : ""}${r.hint}`}</Info> : null}
            </span>
          </th>
          {r.cells.map((c, i) => (
            <td
              key={subjects[i]?.run.id}
              className={`px-3 py-2 tabular-nums ${r.best.includes(i) ? "font-semibold" : ""}`}
            >
              <span className="flex items-center gap-1">
                {c.text}
                {r.best.includes(i) ? (
                  <span className="inline-flex items-center gap-0.5 text-xs font-medium">
                    <Check aria-hidden className="size-3.5" />
                    best
                  </span>
                ) : null}
              </span>
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
