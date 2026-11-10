import { Monitor, Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";

/** Icon button in the top bar: flips between light and dark. The full three-way choice is on Settings. */
export function ThemeToggleButton() {
  const { resolved, setChoice } = useTheme();
  const next = resolved === "dark" ? "light" : "dark";
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Switch to ${next} theme`}
            onClick={() => {
              setChoice(next);
            }}
          />
        }
      >
        {resolved === "dark" ? <Sun /> : <Moon />}
      </TooltipTrigger>
      <TooltipContent>Switch to {next} theme</TooltipContent>
    </Tooltip>
  );
}

const OPTIONS: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match system", icon: Monitor },
];

export function ThemeChoiceGroup() {
  const { choice, setChoice } = useTheme();
  return (
    <div role="radiogroup" aria-label="Theme" className="inline-flex rounded-lg border p-0.5">
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={choice === value}
          onClick={() => {
            setChoice(value);
          }}
          className={cn(
            "inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
            choice === value
              ? "bg-accent font-medium"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Icon className="size-4" aria-hidden />
          {label}
        </button>
      ))}
    </div>
  );
}
