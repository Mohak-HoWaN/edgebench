import { useEffect, useRef } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useVariantLog } from "@/lib/models";

interface Props {
  variantId: number | null;
  title: string;
  /** Keep refreshing while the conversion is still running. */
  live: boolean;
  onClose: () => void;
}

export function LogDialog({ variantId, title, live, onClose }: Props) {
  const log = useVariantLog(variantId, live);
  // Polling stops the moment the conversion ends, so the last poll can be up to a second and a half old: read once more.
  const wasLive = useRef(live);
  const { refetch } = log;
  useEffect(() => {
    if (wasLive.current && !live) void refetch();
    wasLive.current = live;
  }, [live, refetch]);
  return (
    <Dialog
      open={variantId !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            What the converter printed, the end of it if it was long.
          </DialogDescription>
        </DialogHeader>
        <pre
          tabIndex={0}
          aria-label="Converter log"
          className="max-h-[60vh] overflow-auto rounded-md border bg-muted p-3 text-xs leading-relaxed whitespace-pre-wrap"
        >
          {log.isPending
            ? "Loading the log."
            : log.isError
              ? log.error.message
              : log.data || "Nothing was printed yet."}
        </pre>
      </DialogContent>
    </Dialog>
  );
}
