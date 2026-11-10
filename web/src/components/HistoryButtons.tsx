import { ChevronLeft, ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useHistoryPosition } from "@/lib/history";

/**
 * Back and forward through the pages you have been to inside EdgeBench: the same as the browser's own buttons, but always in
 * reach at the top left of the workspace. Back is off on the first page you opened; forward is on only after you went back.
 */
export function HistoryButtons() {
  const navigate = useNavigate();
  const { here, furthest } = useHistoryPosition();
  return (
    <div className="flex items-center" role="group" aria-label="Page history">
      <Button
        variant="ghost"
        size="icon-sm"
        disabled={here <= 0}
        aria-label="Back"
        title="Back to the previous page (Alt+Left)"
        onClick={() => {
          void navigate(-1);
        }}
      >
        <ChevronLeft aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="icon-sm"
        disabled={here >= furthest}
        aria-label="Forward"
        title="Forward to the page you came back from (Alt+Right)"
        onClick={() => {
          void navigate(1);
        }}
      >
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}
