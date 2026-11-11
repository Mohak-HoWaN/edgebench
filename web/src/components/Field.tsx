import { useId, type ReactNode, type SelectHTMLAttributes } from "react";
import { Info } from "@/components/Info";
import { cn } from "@/lib/utils";

const CONTROL =
  "h-8 w-full min-w-0 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

/**
 * A label tied to its control. `help` appears as an "i" beside the label (hover or focus), not as a line under the control.
 * The control is given the generated id; the second argument is kept for callers and is always undefined now.
 */
export function Field({
  label,
  help,
  children,
  className,
}: {
  label: string;
  help?: string;
  children: (id: string, describedBy: string | undefined) => ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <div className={cn("space-y-1", className)}>
      <div className="flex items-center gap-1.5">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        {help ? <Info>{help}</Info> : null}
      </div>
      {children(id, undefined)}
    </div>
  );
}

export function NativeSelect({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(CONTROL, className)} {...props} />;
}
