import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { usePalette } from "@/components/CommandPalette";
import { NAV } from "./nav";

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable)
  );
}

export const SHORTCUTS: { keys: string; does: string }[] = [
  { keys: "Ctrl K  or  Cmd K", does: "Open the command palette" },
  ...NAV.map((n) => ({ keys: `G then ${n.chord.toUpperCase()}`, does: `Go to ${n.label}` })),
  { keys: "Alt Left  /  Alt Right", does: "Back and forward through the pages you visited" },
  {
    keys: "Up  /  Down, then Enter",
    does: "On Results: move between experiments, open the one you are on",
  },
];

/**
 * Does this key press mean `letter`? Case and Caps Lock do not matter. On a layout that types non-Latin characters (so
 * `e.key` is not a Latin letter) the physical key position is used instead; on Dvorak or AZERTY the typed letter wins.
 */
function isKey(e: KeyboardEvent, letter: string): boolean {
  if (/^[a-z,]$/i.test(e.key)) return e.key.toLowerCase() === letter;
  return e.code === (letter === "," ? "Comma" : `Key${letter.toUpperCase()}`);
}

const dialogOpen = (selector = '[role="dialog"], [role="alertdialog"]') =>
  document.querySelector(selector) !== null;

/**
 * Ctrl/Cmd+K opens the palette; "g" followed by a letter within one second jumps to a page. Page shortcuts are ignored
 * while typing and while any dialog is open (they would act on the page behind it); Ctrl+K never opens over a confirm dialog.
 */
export function useShortcuts(): void {
  const navigate = useNavigate();
  useEffect(() => {
    let waitingForSecondKey = false;
    let timer: number | undefined;

    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey) return;
      if ((e.metaKey || e.ctrlKey) && isKey(e, "k")) {
        e.preventDefault();
        if (dialogOpen('[role="alertdialog"]')) return;
        const { open, setOpen } = usePalette.getState();
        setOpen(!open);
        return;
      }
      if (e.metaKey || e.ctrlKey || e.shiftKey || isTyping(e.target) || dialogOpen()) return;
      if (waitingForSecondKey) {
        waitingForSecondKey = false;
        window.clearTimeout(timer);
        const hit = NAV.find((n) => isKey(e, n.chord));
        if (hit) {
          e.preventDefault();
          void navigate(hit.to);
        }
        return;
      }
      if (isKey(e, "g")) {
        waitingForSecondKey = true;
        timer = window.setTimeout(() => {
          waitingForSecondKey = false;
        }, 1000);
      }
    };

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.clearTimeout(timer);
    };
  }, [navigate]);
}
