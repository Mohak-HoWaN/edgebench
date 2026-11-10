import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Input } from "@/components/ui/input";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

export interface ConfirmOptions {
  title: string;
  body: string;
  /** Names the action, e.g. "Reset preferences", never "OK". */
  confirmLabel: string;
  destructive?: boolean;
  /** If set, the action stays disabled until the person types exactly this text (for things that cannot be undone). */
  typeToConfirm?: string;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

export function useConfirm(): Confirm {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error("useConfirm must be used inside <ConfirmProvider>");
  return confirm;
}

/** One shared dialog; `await confirm({...})` resolves true only when the person presses the action button. */
export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const [typed, setTyped] = useState("");
  const settle = useRef<((answer: boolean) => void) | null>(null);

  const confirm = useCallback<Confirm>((next) => {
    settle.current?.(false);
    setTyped("");
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      settle.current = resolve;
    });
  }, []);

  const close = (answer: boolean) => {
    settle.current?.(answer);
    settle.current = null;
    setOptions(null);
  };

  return (
    <ConfirmContext value={confirm}>
      {children}
      <AlertDialog
        open={options !== null}
        onOpenChange={(open) => {
          if (!open) close(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{options?.title}</AlertDialogTitle>
            <AlertDialogDescription>{options?.body}</AlertDialogDescription>
          </AlertDialogHeader>
          {options?.typeToConfirm ? (
            <div className="space-y-2">
              <label htmlFor="confirm-phrase" className="block text-sm">
                To confirm, type <strong className="font-semibold">{options.typeToConfirm}</strong>
              </label>
              <Input
                id="confirm-phrase"
                autoComplete="off"
                value={typed}
                onChange={(e) => {
                  setTyped(e.target.value);
                }}
              />
            </div>
          ) : null}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              variant={options?.destructive ? "destructive" : "default"}
              disabled={options?.typeToConfirm !== undefined && typed !== options.typeToConfirm}
              onClick={() => {
                close(true);
              }}
            >
              {options?.confirmLabel}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext>
  );
}
