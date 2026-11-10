import { Lightbulb } from "lucide-react";
import { Info } from "@/components/Info";

/** A column of sentences worked out from the data on the page: what is fastest, what is tied, what to repeat. */
export function Insights({ items, className }: { items: string[]; className?: string }) {
  if (items.length === 0) return null;
  return (
    <aside aria-label="Insights" className={className}>
      <div className="rounded-lg border bg-muted/30 p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Lightbulb aria-hidden className="size-4 text-muted-foreground" />
          Insights
          <Info>
            Sentences worked out from the results on this page. They change as runs finish, and they
            say when the data is too thin to conclude anything.
          </Info>
        </h3>
        <ul className="space-y-2.5 text-sm">
          {items.map((text) => (
            <li key={text} className="leading-snug">
              {text}
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
