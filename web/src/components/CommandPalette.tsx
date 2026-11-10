import { Monitor, Moon, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { create } from "zustand";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import { NAV } from "@/lib/nav";
import { useTheme } from "@/lib/theme";

export const usePalette = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => {
    set({ open });
  },
}));

export function CommandPalette() {
  const { open, setOpen } = usePalette();
  const navigate = useNavigate();
  const setChoice = useTheme((s) => s.setChoice);

  const run = (action: () => void) => () => {
    setOpen(false);
    action();
  };

  return (
    <CommandDialog
      open={open}
      onOpenChange={setOpen}
      title="Go to"
      description="Jump to a page or change the theme"
    >
      {/* This shadcn version's CommandDialog does not render the cmdk root itself; without <Command> the list has no store. */}
      <Command>
        <CommandInput placeholder="Search pages and actions" />
        <CommandList>
          <CommandEmpty>Nothing matches that.</CommandEmpty>
          <CommandGroup heading="Go to">
            {NAV.map(({ to, label, icon: Icon, chord }) => (
              <CommandItem key={to} value={`go ${label}`} onSelect={run(() => void navigate(to))}>
                <Icon aria-hidden />
                {label}
                <CommandShortcut>G then {chord.toUpperCase()}</CommandShortcut>
              </CommandItem>
            ))}
          </CommandGroup>
          <CommandGroup heading="Theme">
            <CommandItem
              value="theme light"
              onSelect={run(() => {
                setChoice("light");
              })}
            >
              <Sun aria-hidden />
              Light theme
            </CommandItem>
            <CommandItem
              value="theme dark"
              onSelect={run(() => {
                setChoice("dark");
              })}
            >
              <Moon aria-hidden />
              Dark theme
            </CommandItem>
            <CommandItem
              value="theme system match"
              onSelect={run(() => {
                setChoice("system");
              })}
            >
              <Monitor aria-hidden />
              Match system theme
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>
    </CommandDialog>
  );
}
