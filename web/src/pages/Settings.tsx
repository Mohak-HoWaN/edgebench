import { toast } from "sonner";
import { useConfirm } from "@/components/ConfirmProvider";
import { PageHeader, Section } from "@/components/PageHeader";
import { PriorityEditor } from "@/components/PriorityEditor";
import { ThemeChoiceGroup } from "@/components/ThemeControls";
import { Button } from "@/components/ui/button";
import { useHealth } from "@/lib/api";
import { usePriority } from "@/lib/metrics";
import { SHORTCUTS } from "@/lib/shortcuts";
import { useTheme } from "@/lib/theme";

export default function Settings() {
  const confirm = useConfirm();
  const health = useHealth();
  const resetTheme = useTheme((s) => s.reset);
  const resetPriority = usePriority((s) => s.reset);

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
