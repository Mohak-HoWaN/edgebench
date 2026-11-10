import { isRouteErrorResponse, Link, useRouteError } from "react-router-dom";
import { buttonVariants } from "@/components/ui/button";

/** Shown when a page throws, or a page file fails to load (for example after the server was updated mid-session). */
export function RouteError() {
  const error = useRouteError();
  const detail = isRouteErrorResponse(error)
    ? `${String(error.status)} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : "Unknown error";
  return (
    <div role="alert" className="mx-auto max-w-prose px-6 py-16">
      <h1 className="text-2xl font-semibold tracking-tight">This page failed to load</h1>
      <p className="mt-2 text-sm text-muted-foreground">{detail}</p>
      <p className="mt-1 text-sm text-muted-foreground">
        Reloading usually fixes it. If it keeps happening, the server may have been updated; reload
        to get the new version.
      </p>
      <div className="mt-4 flex gap-2">
        <button
          type="button"
          className={buttonVariants({ size: "sm" })}
          onClick={() => {
            window.location.reload();
          }}
        >
          Reload the page
        </button>
        <Link to="/" className={buttonVariants({ size: "sm", variant: "outline" })}>
          Go to the dashboard
        </Link>
      </div>
    </div>
  );
}
