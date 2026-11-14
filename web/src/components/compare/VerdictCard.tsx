import { Star } from "lucide-react";
import { useId } from "react";
import { Info } from "@/components/Info";
import { Input } from "@/components/ui/input";
import type { Subject } from "@/lib/compare/subjects";
import type { Limits, Verdict } from "@/lib/compare/verdict";

/** The three limits as the person types them: percent, milliseconds, megabytes; empty means no limit. */
export interface LimitText {
  acc: string;
  ms: string;
  mb: string;
}

export const toLimits = (t: LimitText): Limits => {
  const num = (s: string) => (s.trim() === "" || Number.isNaN(Number(s)) ? undefined : Number(s));
  const acc = num(t.acc);
  return {
    minAccuracy: acc === undefined ? undefined : acc / 100,
    maxMs: num(t.ms),
    maxMb: num(t.mb),
  };
};

function LimitField({
  label,
  unit,
  value,
  placeholder,
  onChange,
  hint,
}: {
  label: string;
  unit: string;
  value: string;
  placeholder: string;
  onChange: (v: string) => void;
  hint: string;
}) {
  const id = useId();
  return (
    <div className="text-sm">
      <span className="mb-1 flex items-center gap-1.5 font-medium">
        <label htmlFor={id}>{label}</label>
        <Info>{hint}</Info>
      </span>
      <span className="flex items-center gap-1.5">
        <Input
          id={id}
          inputMode="decimal"
          className="w-24"
          value={value}
          placeholder={placeholder}
          onChange={(e) => {
            onChange(e.target.value);
          }}
        />
        <span className="text-muted-foreground">{unit}</span>
      </span>
    </div>
  );
}

/**
 * The answer first: which run to pick, in plain words, and why the others lost, given the limits you set. The limits are two or
 * three numbers (at least this accurate, at most this slow, at most this big); a run that misses one is left out with the reason.
 */
export function VerdictCard({
  verdict,
  limits,
  defaults,
  onLimits,
}: {
  verdict: Verdict;
  limits: LimitText;
  defaults: LimitText;
  onLimits: (next: LimitText) => void;
}) {
  const w = verdict.winner;
  return (
    <section aria-labelledby="verdict-heading" className="rounded-xl border bg-card p-5">
      <h2
        id="verdict-heading"
        className="flex items-center gap-2 text-sm font-semibold text-muted-foreground"
      >
        <Star aria-hidden className="size-4" />
        The answer
      </h2>
      <p className="mt-1 text-xl font-semibold">{verdict.headline}</p>
      {w ? (
        <p className="mt-1 text-sm text-muted-foreground">
          First by your priorities among the runs that meet your limits.
        </p>
      ) : null}
      {verdict.against.length > 0 ? (
        <ul
          className="mt-3 max-w-prose list-disc space-y-1 pl-5 text-sm"
          aria-label="How the pick compares"
        >
          {verdict.against.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      ) : null}
      {verdict.notes.length > 0 ? (
        <ul
          className="mt-3 max-w-prose list-disc space-y-1 border-l-2 border-warn pl-6 text-sm"
          aria-label="Things to keep in mind"
        >
          {verdict.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
      {verdict.failed.length > 0 ? (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer font-medium">
            Left out because they miss a limit ({String(verdict.failed.length)})
          </summary>
          <ul className="mt-2 max-w-prose list-disc space-y-1 pl-5">
            {verdict.failed.map((f) => (
              <li key={f.subject.run.id}>
                {f.subject.long}: {f.reasons.join("; ")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <fieldset className="mt-4 border-t pt-4">
        <legend className="sr-only">Your limits</legend>
        <p className="mb-2 text-sm font-medium">Your limits (leave empty for none)</p>
        <div className="flex flex-wrap gap-5">
          <LimitField
            label="At least this accurate"
            unit="%"
            value={limits.acc}
            placeholder={defaults.acc}
            onChange={(acc) => {
              onLimits({ ...limits, acc });
            }}
            hint="The accuracy score a run must reach. The grey number is the default: the reference run's score minus the drop you allow in Settings."
          />
          <LimitField
            label="At most this slow"
            unit="ms per picture"
            value={limits.ms}
            placeholder="no limit"
            onChange={(ms) => {
              onLimits({ ...limits, ms });
            }}
            hint="The typical time per picture a run may take."
          />
          <LimitField
            label="At most this big"
            unit="MB"
            value={limits.mb}
            placeholder="no limit"
            onChange={(mb) => {
              onLimits({ ...limits, mb });
            }}
            hint="The file size a run may have."
          />
        </div>
      </fieldset>
    </section>
  );
}

export const subjectName = (s: Subject | undefined) => s?.long ?? "";
