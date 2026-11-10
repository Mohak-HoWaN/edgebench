import { Info as InfoIcon } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * A small "i" that explains something on hover or keyboard focus. Static help lives here instead of taking up room on the page;
 * the page keeps its space for things that are worked out from the data. The text is also the button's name, so a screen reader
 * says it when the icon is focused.
 */
export function Info({ children, className }: { children: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <button
            type="button"
            aria-label={children}
            className={cn(
              "inline-flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50",
              className,
            )}
          />
        }
      >
        <InfoIcon aria-hidden className="size-4" />
      </TooltipTrigger>
      <TooltipContent className="max-w-sm items-start text-left leading-snug">
        {children}
      </TooltipContent>
    </Tooltip>
  );
}
