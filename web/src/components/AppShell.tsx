import { LogOut, Search } from "lucide-react";
import { Suspense, useEffect } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { CommandPalette, usePalette } from "@/components/CommandPalette";
import { HistoryButtons } from "@/components/HistoryButtons";
import { Login } from "@/components/Login";
import { StatusPill } from "@/components/StatusPill";
import { ThemeToggleButton } from "@/components/ThemeControls";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useHealth } from "@/lib/api";
import { logOut, useAuth } from "@/lib/auth";
import { useLiveEvents } from "@/lib/connection";
import { GROUP_LABEL, NAV, type NavItem } from "@/lib/nav";
import { useShortcuts } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

function Wordmark() {
  return (
    <span className="flex items-center gap-2 text-base font-semibold tracking-tight">
      <svg viewBox="0 0 20 20" className="size-5 text-primary" aria-hidden fill="currentColor">
        <rect x="2" y="11" width="4" height="7" rx="1" />
        <rect x="8" y="5" width="4" height="13" rx="1" />
        <rect x="14" y="8" width="4" height="10" rx="1" />
      </svg>
      EdgeBench
    </span>
  );
}

function NavGroup({ group }: { group: NavItem["group"] }) {
  const { pathname } = useLocation();
  const items = NAV.filter((n) => n.group === group);
  const label = GROUP_LABEL[group];
  return (
    <div className="space-y-0.5">
      {label ? (
        <p className="px-3 pb-1 pt-4 text-xs font-medium text-muted-foreground">{label}</p>
      ) : null}
      {items.map(({ to, label: text, icon: Icon, sections }) => (
        <div key={to}>
          <NavLink
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                isActive
                  ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
              )
            }
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            {text}
          </NavLink>
          {sections && pathname === to ? (
            <ul
              className="my-1 ml-6 space-y-0.5 border-l pl-3"
              aria-label={`${text}, on this page`}
            >
              {sections.map((s) => (
                <li key={s.id}>
                  <Link
                    to={`${to}#${s.id}`}
                    className="block rounded-md px-2 py-1 text-xs text-sidebar-foreground/70 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground"
                  >
                    {s.label}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading page" className="space-y-4">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-4 w-96 max-w-full" />
      <Skeleton className="mt-8 h-40 w-full max-w-prose" />
    </div>
  );
}

/** Shown by the router on first load, while the first page's code is still downloading. */
export function Splash() {
  return (
    <div className="p-8">
      <PageSkeleton />
    </div>
  );
}

/** A link to a part of a page (`/models#your-models`) scrolls to it; the page may still be loading, so try for a moment. */
function useScrollToHash() {
  const { pathname, hash, key } = useLocation();
  useEffect(() => {
    if (!hash) return;
    let tries = 0;
    let timer: number | undefined;
    const go = () => {
      const el = document.getElementById(hash.slice(1));
      if (el) el.scrollIntoView({ block: "start" });
      else if (tries++ < 20) timer = window.setTimeout(go, 50);
    };
    go();
    return () => {
      window.clearTimeout(timer);
    };
  }, [pathname, hash, key]);
}

/** The app, or the sign-in page when the server has an owner password and this browser has no session. */
export function AppShell() {
  const auth = useAuth();
  if (auth.isPending) return <Splash />;
  if (auth.data?.enabled && !auth.data.signed_in) return <Login />;
  return <Shell signOut={auth.data?.enabled === true} />;
}

function Shell({ signOut }: { signOut: boolean }) {
  useScrollToHash();
  useLiveEvents();
  useShortcuts();
  const health = useHealth();
  const setOpen = usePalette((s) => s.setOpen);

  return (
    <div className="min-h-dvh md:grid md:grid-cols-[14.5rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>

      <aside className="sticky top-0 hidden h-dvh flex-col border-r bg-sidebar md:flex">
        <div className="px-5 pb-2 pt-5">
          <Wordmark />
        </div>
        <nav aria-label="Main" className="flex-1 overflow-y-auto px-2 pb-4">
          <NavGroup group="top" />
          <NavGroup group="setup" />
          <NavGroup group="experiments" />
          <div className="mt-4 border-t pt-4">
            <NavGroup group="bottom" />
          </div>
        </nav>
        <div className="border-t px-2 py-3">
          <StatusPill className="px-3" />
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-10 flex h-12 items-center gap-2 border-b bg-background/90 px-4 backdrop-blur">
          <HistoryButtons />
          <span className="md:hidden">
            <Wordmark />
          </span>
          <div className="ml-auto flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setOpen(true);
              }}
              className="text-muted-foreground"
            >
              <Search aria-hidden />
              {/* The visible text is the accessible name; it stays readable to screen readers when hidden on narrow screens. */}
              <span className="sr-only sm:not-sr-only">Go to</span>
              <kbd className="hidden rounded border px-1.5 text-xs sm:inline">Ctrl K</kbd>
            </Button>
            <ThemeToggleButton />
            {signOut ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void logOut().then(() => {
                    window.location.reload();
                  });
                }}
              >
                <LogOut aria-hidden />
                <span className="sr-only sm:not-sr-only">Sign out</span>
              </Button>
            ) : null}
          </div>
        </header>

        {health.isError ? (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-3 border-b bg-destructive/10 px-6 py-3 text-sm"
          >
            <span>
              EdgeBench cannot reach its server. Check that it is running; this page retries every
              few seconds.
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void health.refetch();
              }}
            >
              Retry now
            </Button>
          </div>
        ) : null}

        <main
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-5xl flex-1 px-6 py-8 outline-none"
        >
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <CommandPalette />
    </div>
  );
}
