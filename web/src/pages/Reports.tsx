import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export default function Reports() {
  return (
    <>
      <PageHeader
        title="Reports"
        hint="Turn finished experiments into a paper in the template you choose."
      />
      <EmptyState title="No reports yet" note="Report writing is not available in this build yet.">
        You pick the experiments, the sections and the paper template, edit the text, then export a
        PDF.
      </EmptyState>
    </>
  );
}
