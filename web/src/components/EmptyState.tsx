import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";

interface Props {
  title: string;
  children: ReactNode;
  /** A real destination. Do not offer a button for something that is not built yet; say so in `note`. */
  action?: { label: string; to: string };
  note?: string;
}

/** An empty screen says what is missing, what to do about it, and what is not available yet. */
export function EmptyState({ title, children, action, note }: Props) {
  return (
    <div className="max-w-prose py-2">
      <h2 className="text-base font-medium">{title}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{children}</p>
      {action ? (
        <Link to={action.to} className={buttonVariants({ size: "sm" }) + " mt-4"}>
          {action.label}
        </Link>
      ) : null}
      {note ? <p className="mt-3 text-sm text-muted-foreground">{note}</p> : null}
    </div>
  );
}
