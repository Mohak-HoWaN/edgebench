import { Check } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { BarsChart, type Group } from "@/components/charts/BarsChart";
import { BoxChart, StageChart } from "@/components/charts/BoxChart";
import { Heatmap } from "@/components/charts/Heatmap";
import { ChartFrame, seriesVar } from "@/components/charts/kit";
import { XYChart, type XYSeries } from "@/components/charts/XYChart";
import * as b from "@/lib/compare/builders";
import * as i from "@/lib/compare/interpret";
import type { Subject } from "@/lib/compare/subjects";
import type { Limits } from "@/lib/compare/verdict";
import { ChartTabs } from "./ChartTabs";
import type { Metric } from "@/lib/metrics";

const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
const pct0 = (n: number) => `${(n * 100).toFixed(0)}%`;
const ms = (n: number) => `${n.toFixed(1)} ms`;
const mb = (n: number) => `${n.toFixed(1)} MB`;

const NEED_RUNS = "Select at least two runs to compare.";
const NEED_ACCURACY =
  "None of the selected runs has an accuracy: they need a dataset with annotations.";

const SELECT = "h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground";

/** A scatter of one run per mark, with the front drawn. */
function scatter(
  points: b.XY[],
  opts: {
    xLabel: string;
    yLabel: string;
    fx: (n: number) => string;
    fy: (n: number) => string;
    tipX: (n: number) => string;
    tipY: (n: number) => string;
    yDomain?: [number, number];
    zone?: { xMax?: number; yMin?: number; label: string };
  },
  aria: string,
) {
  const series: XYSeries[] = points.map((p) => ({
    id: String(p.subject.run.id),
    subject: p.subject,
    label: p.subject.long,
    points: [{ x: p.x, y: p.y }],
    markers: true,
    tag: p.front,
  }));
  const front = points
    .filter((p) => p.front)
    .sort((a, c) => a.x - c.x)
    .map((p) => ({ x: p.x, y: p.y }));
  return <XYChart series={series} front={front} aria={aria} {...opts} />;
}

const tableOf = (head: string[], rows: (string | number)[][]) => ({ head, rows });

export function Scorecard({ subjects, metrics }: { subjects: Subject[]; metrics: Metric[] }) {
  const card = useMemo(() => b.scorecard(subjects, metrics), [subjects, metrics]);
  return (
    <ChartFrame
      id="scorecard"
      title="Scorecard"
      question="Which run wins for my priorities?"
      how="rows follow your priority order (Settings, Metrics you judge by); the bar in a cell is that value against the best in its column (the best fills the bar), and the best in each column is marked."
      lines={i.scoreSentence(
        card,
        metrics.map((m) => m.label),
      )}
      empty={
        subjects.length < 2
          ? NEED_RUNS
          : metrics.length === 0
            ? "Choose the metrics you judge by in Settings."
            : undefined
      }
      table={tableOf(
        ["Run", ...metrics.map((m) => m.label)],
        card.rows.map((r) => [
          r.subject.long,
          ...r.cells.map((c) => (c.value === undefined ? "n/a" : c.metric.format(c.value))),
        ]),
      )}
    >
      <div className="max-w-full overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th scope="col" className="py-2 pr-4 font-medium">
                Rank and run
              </th>
              {metrics.map((m) => (
                <th key={m.key} scope="col" className="py-2 pr-4 font-medium">
                  {m.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {card.rows.map((r, rank) => (
              <tr key={r.subject.run.id} className="border-b align-top">
                <th scope="row" className="py-2 pr-4 text-left font-normal">
                  <span className="mr-2 tabular-nums text-muted-foreground">{rank + 1}</span>
                  <Link
                    to={`/results/${String(r.subject.run.id)}`}
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {r.subject.modelName}, {r.subject.label}
                  </Link>
                </th>
                {r.cells.map((c) => (
                  <td key={c.metric.key} className="min-w-28 py-2 pr-4 tabular-nums">
                    <span className="flex items-center gap-1">
                      {c.value === undefined ? (
                        <span className="text-muted-foreground">n/a</span>
                      ) : (
                        c.metric.format(c.value)
                      )}
                      {c.best ? (
                        <span className="inline-flex items-center gap-0.5 text-xs font-medium">
                          <Check aria-hidden className="size-3.5" />
                          best
                        </span>
                      ) : null}
                    </span>
                    {c.share !== undefined ? (
                      <span className="mt-1 block h-1.5 w-full rounded-full bg-muted" aria-hidden>
                        <span
                          className="block h-1.5 rounded-full"
                          style={{
                            width: `${String(Math.max(6, c.share * 100))}%`,
                            background: seriesVar(r.subject.color),
                          }}
                        />
                      </span>
                    ) : null}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ChartFrame>
  );
}

interface Props {
  subjects: Subject[];
  reference: Subject | undefined;
  metrics: Metric[];
  /** The allowed accuracy drop, in points. */
  band: number;
  limits: Limits;
  tab: string;
  onTab: (tab: string) => void;
}

export function CompareCharts({ subjects, reference, metrics, band, limits, tab, onTab }: Props) {
  const [cls, setCls] = useState<string>("");
  const [confusionId, setConfusionId] = useState<number | null>(null);
  const many = subjects.length >= 2;

  const accSpeed = useMemo(() => b.accuracySpeed(subjects), [subjects]);
  const sizeAcc = useMemo(() => b.sizeAccuracy(subjects), [subjects]);
  const sizeSpd = useMemo(() => b.sizeSpeed(subjects), [subjects]);
  const boxes = useMemo(() => b.latencyBoxes(subjects), [subjects]);
  const traces = useMemo(() => b.overTime(subjects), [subjects]);
  const stageRows = useMemo(() => b.stages(subjects), [subjects]);
  const threads = useMemo(() => b.threadLines(subjects), [subjects]);
  const speed = useMemo(() => b.speedups(subjects, reference), [subjects, reference]);
  const drift = useMemo(() => b.drifts(subjects, reference, band), [subjects, reference, band]);
  const heat = useMemo(() => b.classHeat(subjects), [subjects]);
  const classes = useMemo(() => b.classesWithCurves(subjects), [subjects]);
  const classOrNull = cls === "" ? null : cls;
  const pr = useMemo(() => b.prLines(subjects, classOrNull), [subjects, classOrNull]);
  const f1 = useMemo(() => b.f1Lines(subjects, classOrNull), [subjects, classOrNull]);
  const hists = useMemo(() => b.scoreHists(subjects), [subjects]);
  const machines = useMemo(() => b.machine(subjects), [subjects]);
  const pairs = useMemo(() => b.devicePairs(subjects), [subjects]);
  const sources = useMemo(() => b.bySource(subjects), [subjects]);
  const withConfusion = subjects.filter((s) => b.confusion(s) !== undefined);
  const shown =
    withConfusion.find((s) => s.run.id === confusionId) ??
    (reference && withConfusion.includes(reference) ? reference : withConfusion[0]);
  const conf = b.confusion(shown);
  const refHist = hists.find((h) => h.subject === reference) ?? hists[0];
  const noCurves =
    "These runs did not record curves (runs made before this was added). Run them again to get this chart.";

  const lineSeries = (
    lines: b.Line[],
    label: (l: b.Line) => string = (l) => l.subject.long,
  ): XYSeries[] =>
    lines.map((l) => ({
      id: String(l.subject.run.id),
      subject: l.subject,
      label: label(l),
      points: l.points,
      line: true,
      peak: l.peak,
    }));

  const bars = (
    rows: { subject: Subject; value: number; half?: number; flag?: boolean; note?: string }[],
  ): Group[] =>
    rows.map((r) => ({
      label: r.subject.cat,
      bars: [
        {
          key: String(r.subject.run.id),
          subject: r.subject,
          value: r.value,
          half: r.half,
          flag: r.flag,
          note: r.note,
        },
      ],
    }));

  const frames: Record<string, ReactNode> = {
    scorecard: <Scorecard subjects={subjects} metrics={metrics} />,
    "accuracy-speed": (
      <ChartFrame
        id="accuracy-speed"
        title="Accuracy against speed"
        question="Which run gives the best accuracy for its speed?"
        how="left is faster, up is more accurate, so the best places are top-left. The grey line joins the runs that no other run beats on both; the green area is where your limits are met."
        lines={[
          ...i.front(accSpeed, { x: "a speed", y: "an accuracy" }),
          ...i.accuracyFlat(accSpeed),
        ]}
        empty={
          accSpeed.length === 0
            ? "None of the selected runs has both a speed and an accuracy."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "Typical time", "Accuracy score", "A best trade-off"],
          accSpeed.map((p) => [p.subject.long, ms(p.x), pct(p.y), p.front ? "Yes" : "No"]),
        )}
      >
        {scatter(
          accSpeed,
          {
            xLabel: "Median time per image (ms), lower is faster",
            yLabel: "mAP50-95, higher is more accurate",
            fx: (n) => String(n),
            fy: pct0,
            tipX: ms,
            tipY: pct,
            zone: { xMax: limits.maxMs, yMin: limits.minAccuracy, label: "Meets your limits" },
          },
          "Accuracy against speed, one mark per run",
        )}
      </ChartFrame>
    ),
    "size-accuracy": (
      <ChartFrame
        id="size-accuracy"
        title="Size against accuracy"
        question="Is a smaller file worth it?"
        how="left is a smaller file, up is more accurate, read like the chart above."
        lines={[
          ...i.front(sizeAcc, { x: "a file size", y: "an accuracy" }),
          ...i.sizeCost(sizeAcc),
        ]}
        empty={
          sizeAcc.length === 0
            ? "None of the selected runs has both a file size and an accuracy."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "File size", "mAP50-95"],
          sizeAcc.map((p) => [p.subject.long, mb(p.x), pct(p.y)]),
        )}
      >
        {scatter(
          sizeAcc,
          {
            xLabel: "File size (MB), smaller is left",
            yLabel: "mAP50-95",
            fx: (n) => String(n),
            fy: pct0,
            tipX: mb,
            tipY: pct,
          },
          "Size against accuracy",
        )}
      </ChartFrame>
    ),
    "size-speed": (
      <ChartFrame
        id="size-speed"
        title="Size against speed"
        question="Does a smaller file run faster?"
        how="left is a smaller file, down is faster. The line joins the runs that are both smaller and faster than any other."
        lines={i.front(sizeSpd, { x: "a file size", y: "a speed" })}
        empty={
          sizeSpd.length === 0
            ? "None of the selected runs has both a file size and a speed."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "File size", "Median time"],
          sizeSpd.map((p) => [p.subject.long, mb(p.x), ms(p.y)]),
        )}
      >
        {scatter(
          sizeSpd,
          {
            xLabel: "File size (MB)",
            yLabel: "Median time per image (ms), lower is faster",
            fx: (n) => String(n),
            fy: (n) => String(n),
            tipX: mb,
            tipY: ms,
          },
          "Size against speed",
        )}
      </ChartFrame>
    ),
    "latency-distribution": (
      <ChartFrame
        id="latency-distribution"
        title="Speed spread"
        question="How steady is the speed?"
        how="the box is the middle half of the images, the line through it the median, the whiskers the rest, and dots are outliers. A tall box means unpredictable time."
        lines={i.spread(boxes)}
        empty={
          boxes.length === 0
            ? "These runs did not keep their per-image timings (runs made before repeats were recorded). Run them again."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "Images", "Median", "Middle half", "p99", "Outliers"],
          boxes.map((x) => [
            x.subject.long,
            x.n,
            ms(x.median),
            `${ms(x.q1)} to ${ms(x.q3)}`,
            ms(x.p99),
            x.outliers.length,
          ]),
        )}
      >
        <BoxChart boxes={boxes} aria="Latency distribution, one box per run" />
      </ChartFrame>
    ),
    "latency-over-run": (
      <ChartFrame
        id="latency-over-run"
        title="Speed during the run"
        question="Does it slow down as it warms up?"
        how="time per image (smoothed over 9) against the order the images ran in. A flat line is steady; a climb is heat; a staircase is the operating system moving the work. Dotted lines mark the start of each repeat."
        lines={i.warmth(traces)}
        empty={
          traces.length === 0
            ? "These runs did not keep their per-image timings. Run them again."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "First 10 (median)", "Last quarter (median)"],
          traces.map((t) => {
            const y = t.points.map((p) => p.y);
            const q = Math.max(1, Math.floor(y.length / 4));
            const med = (v: number[]) =>
              [...v].sort((p, r) => p - r)[Math.floor(v.length / 2)] ?? 0;
            return [t.subject.long, ms(med(y.slice(0, 10))), ms(med(y.slice(-q)))];
          }),
        )}
      >
        <XYChart
          series={lineSeries(traces)}
          vlines={(traces[0]?.starts ?? []).slice(1).map((x) => ({ x }))}
          xLabel="Image number"
          yLabel="Time per image (ms)"
          fx={(n) => String(Math.round(n))}
          fy={(n) => n.toFixed(1)}
          aria="Time per image over the run, one line per run"
        />
      </ChartFrame>
    ),
    "where-time-goes": (
      <ChartFrame
        id="where-time-goes"
        title="Where the time goes"
        question="Is it the model that is slow?"
        how="each bar is one image's mean time split into preprocess, the model and postprocess."
        lines={i.bottleneck(stageRows)}
        empty={
          stageRows.length === 0 ? "These runs did not record their stage timings." : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "Preprocess", "Model", "Postprocess"],
          stageRows.map((r) => [r.subject.long, ms(r.pre), ms(r.model), ms(r.post)]),
        )}
      >
        <StageChart rows={stageRows} aria="Where the time goes, one bar per run" />
      </ChartFrame>
    ),
    threads: (
      <ChartFrame
        id="threads"
        title="Speed against threads"
        question="How many threads are worth using?"
        how="time per image against the number of threads, one line for each model and variant. Where the line flattens, extra threads buy nothing."
        lines={i.threading(threads)}
        empty={
          threads.length === 0
            ? "Select runs of the same variant made with different thread counts (a thread sweep) to see this."
            : undefined
        }
        subjects={threads.map((l) => l.subject)}
        table={tableOf(
          ["Line", "Threads", "Median time"],
          threads.flatMap((l) => l.points.map((p) => [l.label, p.x, ms(p.y)])),
        )}
      >
        <XYChart
          series={threads.map((l) => ({
            id: l.label,
            subject: l.subject,
            label: l.label,
            points: l.points,
            line: true,
            markers: true,
          }))}
          xLabel="Threads"
          yLabel="Median time per image (ms)"
          fx={(n) => String(n)}
          fy={(n) => n.toFixed(1)}
          aria="Speed against threads"
        />
      </ChartFrame>
    ),
    "speed-up": (
      <ChartFrame
        id="speed-up"
        title="Speed-up over the reference"
        question={`How much faster than ${reference ? reference.long : "the reference"} is each run?`}
        how="1.0 is the reference; above 1 is faster. The whisker is the doubt about the number (the 95% interval of both runs)."
        lines={i.speedupFlags(speed)}
        empty={
          !many
            ? NEED_RUNS
            : speed.length === 0
              ? "The reference run has no valid speed."
              : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "Speed-up", "Plus or minus"],
          speed.map((r) => [
            r.subject.long,
            `${r.ratio.toFixed(2)}x`,
            r.half === undefined ? "n/a" : r.half.toFixed(2),
          ]),
        )}
      >
        <BarsChart
          groups={bars(
            speed.map((r) => ({
              subject: r.subject,
              value: r.ratio,
              half: r.half,
              flag: r.crossesOne,
            })),
          )}
          baseline={1}
          refLine={{ y: 1, label: "reference" }}
          yLabel="Speed-up (times)"
          fy={(n) => `${n.toFixed(2)}x`}
          aria="Speed-up over the reference, one bar per run"
        />
      </ChartFrame>
    ),
    devices: (
      <ChartFrame
        id="devices"
        title="One machine against another"
        question="How much slower is one machine than another?"
        how="paired bars: the same model, variant and settings on each device, in ms per image. The ratio is in the sentence."
        lines={i.devices(pairs)}
        empty={
          pairs.length === 0
            ? "Select the same run made on two devices (for example the PC and a Pi) to see this."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "Device", "Median time"],
          pairs.flatMap((p) => p.devices.map((d) => [p.title, d.device, ms(d.ms)])),
        )}
      >
        <BarsChart
          groups={pairs.map((p) => ({
            label: p.title.replace(/, /g, " · "),
            bars: p.devices.map((d) => ({
              key: `${p.title}${d.device}`,
              subject: d.subject,
              value: d.ms,
              tag: d.device,
            })),
          }))}
          yLabel="Median time per image (ms)"
          fy={(n) => n.toFixed(1)}
          aria="Device comparison, paired bars"
        />
      </ChartFrame>
    ),
    drift: (
      <ChartFrame
        id="drift"
        title="Accuracy change"
        question={`Did converting or quantizing hurt accuracy, compared with ${reference ? reference.long : "the reference"}?`}
        how={`bars are the change in mAP50-95 in points. The shaded band is the drop you allow (${String(band)} points, Settings); bars inside it are harmless.`}
        lines={i.driftFlags(drift, band)}
        empty={
          !many ? NEED_RUNS : drift.length === 0 ? "The reference run has no accuracy." : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "Change (points)", "Outside the band"],
          drift.map((r) => [
            r.subject.long,
            r.points.toFixed(1),
            r.zero ? "found nothing" : r.outside ? "yes" : "no",
          ]),
        )}
      >
        <BarsChart
          groups={bars(
            drift.map((r) => ({ subject: r.subject, value: r.points, flag: r.outside || r.zero })),
          )}
          band={{ lo: -band, hi: band, label: `allowed: ${String(band)} points` }}
          yLabel="mAP50-95 change (points)"
          fy={(n) => n.toFixed(1)}
          aria="Accuracy drift against the reference, one bar per run"
        />
      </ChartFrame>
    ),
    "per-class": (
      <ChartFrame
        id="per-class"
        title="Accuracy per product"
        question="Which products break, and under which run?"
        how="darker is more accurate (mAP50-95 for that class). Look down a column for a class that fades; the number of labelled examples is under the class name."
        lines={i.classFlags(heat)}
        empty={heat.classes.length === 0 ? NEED_ACCURACY : undefined}
        table={tableOf(
          ["Class", ...subjects.map((s) => s.long)],
          heat.classes.map((c) => [
            c.name,
            ...c.cells.map((v) => (v === undefined ? "n/a" : pct(v))),
          ]),
        )}
      >
        <Heatmap
          rowHeader="Class"
          columns={subjects.map((s) => s.cat)}
          aria="Accuracy per class, classes by runs"
          rows={heat.classes.map((c) => ({
            label: c.name,
            sub: `${String(c.instances)} examples`,
            cells: c.cells.map((v) => (v === undefined ? undefined : { value: v, text: pct(v) })),
          }))}
        />
      </ChartFrame>
    ),
    confusion: (
      <>
        <ChartFrame
          id="confusion"
          title="What is mistaken for what"
          question="What is mistaken for what?"
          how="rows are the truth, columns the answer; the diagonal is right. The last row and column are nothing (a miss, a false alarm). Cells are shaded by their share of the row."
          lines={conf ? i.confusionFlags(conf) : []}
          empty={
            !conf
              ? "None of the selected runs has a confusion matrix: they need a dataset with annotations."
              : undefined
          }
          controls={
            withConfusion.length > 1 ? (
              <label className="flex items-center gap-2 text-sm">
                Run
                <select
                  className={SELECT}
                  value={shown?.run.id}
                  onChange={(e) => {
                    setConfusionId(Number(e.target.value));
                  }}
                >
                  {withConfusion.map((s) => (
                    <option key={s.run.id} value={s.run.id}>
                      {s.long}
                    </option>
                  ))}
                </select>
              </label>
            ) : undefined
          }
          table={
            conf
              ? tableOf(
                  ["Truth", ...conf.labels],
                  conf.matrix.map((row, k) => [conf.labels[k] ?? "", ...row]),
                )
              : undefined
          }
        >
          {conf ? (
            <Heatmap
              rowHeader="Truth ↓   Answer →"
              columns={conf.labels.map((l) => l.replace(/_/g, " · "))}
              aria={`Confusion matrix of ${shown?.long ?? "a run"}`}
              rows={conf.matrix.map((row, k) => {
                const total = row.reduce((a, c) => a + c, 0);
                return {
                  label: conf.labels[k] ?? "",
                  cells: row.map((v) =>
                    v === 0 && total === 0
                      ? undefined
                      : { value: total ? v / total : 0, text: String(v) },
                  ),
                };
              })}
            />
          ) : null}
        </ChartFrame>
        {shown ? (
          <p className="mt-2 text-sm">
            <Link
              to={`/results/${String(shown.run.id)}#failures`}
              className="text-primary underline underline-offset-4"
            >
              See the actual pictures {shown.long} gets wrong
            </Link>
          </p>
        ) : null}
      </>
    ),
    "pr-curve": (
      <ChartFrame
        id="pr-curve"
        title="Right detections against objects found"
        question="How does the trade-off move with the confidence cut-off?"
        how="each line is a run as the cut-off falls from 1 (left of the line's start) to 0. A line closer to the top right is better. This is a view only: nothing here changes a threshold."
        lines={i.steepness(pr)}
        empty={pr.length === 0 ? noCurves : undefined}
        subjects={subjects}
        controls={
          classes.length > 0 ? (
            <label className="flex items-center gap-2 text-sm">
              Class
              <select
                className={SELECT}
                value={cls}
                onChange={(e) => {
                  setCls(e.target.value);
                }}
              >
                <option value="">All classes (their mean)</option>
                {classes.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
          ) : undefined
        }
        table={tableOf(
          ["Run", "Best precision", "Best recall"],
          pr.map((l) => [
            l.subject.long,
            pct(Math.max(...l.points.map((p) => p.y))),
            pct(Math.max(...l.points.map((p) => p.x))),
          ]),
        )}
      >
        <XYChart
          series={lineSeries(pr)}
          xLabel="Recall"
          yLabel="Precision"
          fx={pct0}
          fy={pct0}
          xDomain={[0, 1]}
          yDomain={[0, 1]}
          aria="Precision against recall, one line per run"
        />
      </ChartFrame>
    ),
    "f1-curve": (
      <ChartFrame
        id="f1-curve"
        title="The best cut-off"
        question="Where is the best operating point?"
        how="F1 balances false alarms and misses. The mark on each line is its peak: the cut-off where the two balance. The dotted line is the 0.25 the counts elsewhere on this site use. View only."
        lines={i.peaks(f1)}
        empty={f1.length === 0 ? noCurves : undefined}
        subjects={subjects}
        table={tableOf(
          ["Run", "Peak F1", "At confidence"],
          f1.map((l) => [
            l.subject.long,
            pct(l.points[l.peak ?? 0]?.y ?? 0),
            (l.points[l.peak ?? 0]?.x ?? 0).toFixed(2),
          ]),
        )}
      >
        <XYChart
          series={lineSeries(f1)}
          vlines={[{ x: 0.25, label: "0.25" }]}
          xLabel="Confidence cut-off"
          yLabel="F1"
          fx={(n) => n.toFixed(1)}
          fy={pct0}
          xDomain={[0, 1]}
          yDomain={[0, 1]}
          aria="F1 against confidence, one line per run"
        />
      </ChartFrame>
    ),
    "score-distribution": (
      <ChartFrame
        id="score-distribution"
        title="How sure the model is"
        question="Did quantization change how sure the model is?"
        how="the share of a run's detections at each confidence. Compare the shapes: a whole line shifted to the left means the model is less sure."
        lines={i.scoreShift(hists, refHist?.subject, refHist?.mean)}
        empty={hists.length === 0 ? noCurves : undefined}
        subjects={subjects}
        table={tableOf(
          ["Run", "Mean confidence"],
          hists.map((h) => [h.subject.long, pct(h.mean)]),
        )}
      >
        <XYChart
          series={hists.map((h) => ({
            id: String(h.subject.run.id),
            subject: h.subject,
            label: h.subject.long,
            line: true,
            points: h.share.map((y, k) => ({ x: (k + 0.5) / h.share.length, y })),
          }))}
          xLabel="Confidence of a detection"
          yLabel="Share of the run's detections"
          fx={(n) => n.toFixed(1)}
          fy={pct0}
          xDomain={[0, 1]}
          aria="Score distribution, one line per run"
        />
      </ChartFrame>
    ),
    "capture-source": (
      <ChartFrame
        id="capture-source"
        title="Accuracy by where the picture came from"
        question="Does it work as well on the shop's camera as on phone photos?"
        how="bars of one run side by side for each source of picture (the camera, the phone, other)."
        lines={i.sources(sources)}
        empty={
          sources.sources.length === 0
            ? "These runs did not record accuracy by source (runs made before this was added, or a dataset with one source). Run them again."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Source", ...subjects.map((s) => s.long)],
          sources.sources.map((x) => [
            x.name,
            ...x.cells.map((c) => (c ? `${pct(c.map)} (${String(c.images)} pictures)` : "n/a")),
          ]),
        )}
      >
        <BarsChart
          groups={sources.sources.map((x) => ({
            label: x.name,
            bars: x.cells.flatMap((c, k) => {
              const subject = subjects[k];
              return c && subject
                ? [
                    {
                      key: `${x.name}${String(k)}`,
                      subject,
                      value: c.map,
                      note: `${String(c.images)} pictures`,
                    },
                  ]
                : [];
            }),
          }))}
          yLabel="mAP50-95"
          fy={pct0}
          domain={[0, 1]}
          aria="Accuracy by capture source"
        />
      </ChartFrame>
    ),
    temperature: (
      <ChartFrame
        id="temperature"
        title="Heat and clock speed"
        question="Did the device overheat or slow itself?"
        how="two lines over the run, temperature then clock speed. Temperature up while the clock goes down is throttling. Grey bands are repeats that were left out; dotted lines are the moments the machine said it was throttling."
        lines={i.heat(machines)}
        empty={
          machines.length === 0
            ? "These runs did not record temperature and clock over time (runs made before this was added, or telemetry was off). Run them again."
            : undefined
        }
        subjects={subjects}
        table={tableOf(
          ["Run", "Hottest", "Lowest clock", "Throttle readings"],
          machines.map((m) => [
            m.subject.long,
            `${String(Math.max(...m.temp.filter((v): v is number => v !== null), 0))} °C`,
            `${String(Math.min(...m.clock.filter((v): v is number => v !== null)))} MHz`,
            m.throttledAt.length,
          ]),
        )}
      >
        {(["temp", "clock"] as const).map((k) => (
          <div key={k} className="mb-3">
            <XYChart
              height={240}
              series={machines.map((m) => ({
                id: `${k}${String(m.subject.run.id)}`,
                subject: m.subject,
                label: m.subject.long,
                line: true,
                points: m.t.flatMap((x, n) => {
                  const y = m[k][n];
                  return y == null ? [] : [{ x, y }];
                }),
              }))}
              bands={(machines[0]?.repeats ?? [])
                .filter((r) => !r.valid)
                .map((r) => ({ from: r.start, to: r.end }))}
              vlines={machines.flatMap((m) => m.throttledAt.slice(0, 3)).map((x) => ({ x }))}
              xLabel="Seconds into the run"
              yLabel={k === "temp" ? "Temperature (°C)" : "Clock (MHz)"}
              fx={(n) => String(Math.round(n))}
              fy={(n) => String(Math.round(n))}
              aria={k === "temp" ? "Temperature over the run" : "CPU clock over the run"}
            />
          </div>
        ))}
      </ChartFrame>
    ),
  };
  return <ChartTabs frames={frames} tab={tab} onTab={onTab} />;
}
