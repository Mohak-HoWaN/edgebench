import { toast } from "sonner";
import { useConfirm } from "@/components/ConfirmProvider";
import { Field } from "@/components/Field";
import { PageHeader, Section } from "@/components/PageHeader";
import { PriorityEditor } from "@/components/PriorityEditor";
import { ThemeChoiceGroup } from "@/components/ThemeControls";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useHealth } from "@/lib/api";
import { useDriftLimits } from "@/lib/drift";
import { usePriority } from "@/lib/metrics";
import { SHORTCUTS } from "@/lib/shortcuts";
import { useTheme } from "@/lib/theme";

/** How far a converted variant may drift from the PyTorch baseline before the accuracy check fails it. */
function DriftLimitsEditor() {
  const limits = useDriftLimits();
  return (
    <div className="grid max-w-prose gap-4 sm:grid-cols-2">
      <Field
        label="Largest mAP drop (points)"
        help="A variant whose mAP50 is lower than the PyTorch baseline's by more than this fails. 5 means five points on the 0-100 scale."
      >
        {(id, describedBy) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            type="number"
            inputMode="decimal"
            min={0}
            max={100}
            step={0.5}
            value={limits.maxMapDropPoints}
            onChange={(e) => {
              const n = Number(e.target.value);
              if (Number.isFinite(n) && n >= 0 && n <= 100)
                limits.set({
                  maxMapDropPoints: n,
                  minAgreement: limits.minAgreement,
                });
            }}
          />
        )}
      </Field>
      <Field
        label="Lowest box agreement"
        help="For every detection the PyTorch baseline made, how well the variant's best box overlaps it, averaged (a missed object counts as 0). 1 is identical; a model that finds nothing scores 0 and always fails."
      >
        {(id, describedBy) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            type="number"
            inputMode="decimal"
            min={0}
            max={1}
            step={0.01}
            value={limits.minAgreement}
            onChange={(e) => {
              const n = Number(e.target.value);
              if (Number.isFinite(n) && n >= 0 && n <= 1)
                limits.set({
                  maxMapDropPoints: limits.maxMapDropPoints,
                  minAgreement: n,
                });
            }}
          />
        )}
      </Field>
    </div>
  );
}

export default function Settings() {
  const confirm = useConfirm();
  const health = useHealth();
  const resetTheme = useTheme((s) => s.reset);
  const resetPriority = usePriority((s) => s.reset);
  const resetLimits = useDriftLimits((s) => s.reset);

  const resetPreferences = async () => {
    const ok = await confirm({
      title: "Reset interface preferences?",
      body: "This returns the theme to match your system and the result priorities to the defaults. Your models, datasets and results are not touched.",
      confirmLabel: "Reset preferences",
      destructive: true,
    });
    if (!ok) return;
    resetTheme();
    resetPriority();
    resetLimits();
    toast.success("Interface preferences reset");
  };

  return (
    <>
      <PageHeader title="Settings" hint="How EdgeBench looks and behaves in this browser." />

      <Section title="Appearance" id="appearance">
        <ThemeChoiceGroup />
      </Section>

      <Section
        title="Metrics you judge by"
        id="metrics"
        hint="Results are ranked by the first metric, the columns follow this order, and a tie on one metric is settled by the next. None of these is the one right way to judge a model: pick what matters for what the model is for."
      >
        <PriorityEditor />
      </Section>

      <Section
        title="Accuracy check"
        id="accuracy-check"
        hint="A converted model (especially INT8) can run faster and quietly get worse, or stop finding anything at all. Experiments that include the PyTorch baseline check each variant against it, and these limits decide pass or fail. The defaults come from one measurement (yolo11n on COCO128); set them for your own data and how much loss you can accept."
      >
        <DriftLimitsEditor />
      </Section>

      <Section
        title="Keyboard shortcuts"
        id="shortcuts"
        hint="Page shortcuts are ignored while you are typing in a field."
      >
        <dl className="grid max-w-prose grid-cols-[12rem_1fr] gap-y-2 text-sm">
          {SHORTCUTS.map(({ keys, does }) => (
            <div key={keys} className="contents">
              <dt>
                <kbd className="rounded border px-1.5 py-0.5 text-xs">{keys}</kbd>
              </dt>
              <dd className="text-muted-foreground">{does}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title="About this server" id="about">
        <p className="text-sm">
          {health.data
            ? `EdgeBench ${health.data.version}, database ${health.data.db.ok ? "ready" : "not available"}.`
            : "Reading server details."}
        </p>
      </Section>

      <Section
        title="Interface data"
        id="interface-data"
        hint="This browser remembers your theme and your metrics. Resetting does not change anything on the server."
      >
        <Button
          variant="destructive"
          size="sm"
          onClick={() => {
            void resetPreferences();
          }}
        >
          Reset preferences
        </Button>
      </Section>
    </>
  );
}
