import { Link } from "react-router-dom";
import { ConverterBanner } from "@/components/ConverterBanner";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader, Section } from "@/components/PageHeader";
import { UploadZone } from "@/components/UploadZone";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCount } from "@/lib/format";
import { progressText, useModels } from "@/lib/models";

export default function Models() {
  const models = useModels();
  return (
    <>
      <PageHeader
        title="Models"
        hint="Upload a PyTorch model and EdgeBench converts it to every format and precision you can benchmark."
      />
      <ConverterBanner />
      <Section title="Add a model" id="add-model">
        <UploadZone />
      </Section>
      <Section title="Your models" id="your-models">
        {models.isPending ? (
          <div aria-busy="true" aria-label="Loading models" className="space-y-2">
            <Skeleton className="h-10 w-full max-w-prose" />
            <Skeleton className="h-10 w-full max-w-prose" />
          </div>
        ) : models.isError ? (
          <p className="text-sm">The list of models could not be loaded: {models.error.message}</p>
        ) : models.data.length === 0 ? (
          <EmptyState title="No models yet">
            Upload a model above. Each one shows the status, size and conversion time of every
            variant.
          </EmptyState>
        ) : (
          <ul className="max-w-prose divide-y border-y">
            {models.data.map((m) => (
              <li key={m.id}>
                <Link to={`/models/${String(m.id)}`} className="block py-3 hover:bg-accent/50">
                  <span className="font-medium">{m.name}</span>
                  <span className="block text-sm text-muted-foreground">
                    {[
                      m.task,
                      m.class_names ? `${String(m.class_names.length)} classes` : null,
                      m.parameters ? `${formatCount(m.parameters)} parameters` : null,
                    ]
                      .filter(Boolean)
                      .join(", ") || m.filename}
                  </span>
                  <span className="block text-sm">{progressText(m)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}
