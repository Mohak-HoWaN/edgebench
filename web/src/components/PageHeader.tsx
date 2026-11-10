import { useEffect, useId, type ReactNode } from "react";
import { Info } from "@/components/Info";

interface Props {
  title: string;
  /** What the page is for: shown on hover of the "i" next to the title, so it does not take room on the page. */
  hint?: string;
  /** A line that is worked out from the data (counts, notes); static help belongs in `hint`. */
  children?: ReactNode;
}

export function PageHeader({ title, hint, children }: Props) {
  useEffect(() => {
    document.title = `${title} - EdgeBench`;
  }, [title]);
  return (
    <header className="mb-8 max-w-prose">
      <div className="flex items-center gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {hint ? <Info>{hint}</Info> : null}
      </div>
      {children ? <p className="mt-1 text-sm text-muted-foreground">{children}</p> : null}
    </header>
  );
}

/**
 * A titled block of a page, separated from the next by a rule rather than boxed in a card. `id` makes it a target of the
 * sidebar's links; `hint` is the "i" next to the title.
 */
export function Section({
  title,
  children,
  id,
  hint,
}: {
  title: string;
  children: ReactNode;
  id?: string;
  hint?: string;
}) {
  const headingId = useId();
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className="scroll-mt-16 border-t py-6 first:border-t-0 first:pt-0"
    >
      <h2 id={headingId} className="mb-4 flex items-center gap-2 text-sm font-semibold">
        {title}
        {hint ? <Info>{hint}</Info> : null}
      </h2>
      {children}
    </section>
  );
}
