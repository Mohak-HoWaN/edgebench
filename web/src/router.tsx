import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { AppShell, Splash } from "@/components/AppShell";
import { RouteError } from "@/components/RouteError";
import { trackHistory } from "@/lib/history";

/** Each page is its own chunk; the shell shows a skeleton while one loads. */
const page = (
  load: () => Promise<{ default: React.ComponentType }>,
): Pick<RouteObject, "lazy"> => ({
  lazy: async () => ({ Component: (await load()).default }),
});

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    HydrateFallback: Splash,
    errorElement: <RouteError />,
    children: [
      { index: true, ...page(() => import("@/pages/Dashboard")) },
      { path: "models", ...page(() => import("@/pages/Models")) },
      { path: "models/:id", ...page(() => import("@/pages/ModelDetail")) },
      { path: "datasets", ...page(() => import("@/pages/Datasets")) },
      { path: "datasets/:id", ...page(() => import("@/pages/DatasetDetail")) },
      { path: "devices", ...page(() => import("@/pages/Devices")) },
      { path: "experiments/new", ...page(() => import("@/pages/NewExperiment")) },
      { path: "experiments/:id", ...page(() => import("@/pages/ExperimentDetail")) },
      { path: "results", ...page(() => import("@/pages/Results")) },
      { path: "compare", ...page(() => import("@/pages/Compare")) },
      { path: "results/:id", ...page(() => import("@/pages/RunDetail")) },
      { path: "reports", ...page(() => import("@/pages/Reports")) },
      { path: "settings", ...page(() => import("@/pages/Settings")) },
      { path: "*", ...page(() => import("@/pages/NotFound")) },
    ],
  },
]);

trackHistory(router);
