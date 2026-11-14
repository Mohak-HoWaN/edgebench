import {
  BarChart3,
  Cpu,
  Database,
  FileText,
  FlaskConical,
  LayoutDashboard,
  type LucideIcon,
  Package,
  Settings,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Second key of the "g then ..." shortcut. */
  chord: string;
  group: "top" | "setup" | "experiments" | "bottom";
  /** The parts of the page, shown under it in the sidebar while you are on it; each is a link to that part. */
  sections?: { id: string; label: string }[];
}

/** Single source for the sidebar, the command palette and the keyboard shortcuts. */
export const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, chord: "d", group: "top" },
  {
    to: "/models",
    label: "Models",
    icon: Package,
    chord: "m",
    group: "setup",
    sections: [
      { id: "add-model", label: "Add a model" },
      { id: "your-models", label: "Your models" },
    ],
  },
  {
    to: "/datasets",
    label: "Datasets",
    icon: Database,
    chord: "s",
    group: "setup",
    sections: [
      { id: "create-dataset", label: "Create a dataset" },
      { id: "your-datasets", label: "Your datasets" },
      { id: "other-ways", label: "Other ways in" },
    ],
  },
  {
    to: "/devices",
    label: "Devices",
    icon: Cpu,
    chord: "v",
    group: "setup",
    sections: [
      { id: "add-device", label: "Add a device" },
      { id: "your-devices", label: "Your devices" },
    ],
  },
  {
    to: "/experiments/new",
    label: "New experiment",
    icon: FlaskConical,
    chord: "n",
    group: "experiments",
    sections: [
      { id: "exp-name", label: "Name it" },
      { id: "exp-models", label: "Models and variants" },
      { id: "exp-dataset-device", label: "Dataset and device" },
      { id: "exp-settings", label: "Settings" },
      { id: "exp-sweep", label: "Try several settings" },
      { id: "exp-plan", label: "What this will run" },
    ],
  },
  { to: "/results", label: "Results", icon: BarChart3, chord: "r", group: "experiments" },
  { to: "/reports", label: "Reports", icon: FileText, chord: "p", group: "experiments" },
  {
    to: "/settings",
    label: "Settings",
    icon: Settings,
    chord: ",",
    group: "bottom",
    sections: [
      { id: "appearance", label: "Appearance" },
      { id: "metrics", label: "Metrics you judge by" },
      { id: "accuracy-check", label: "Accuracy check" },
      { id: "shortcuts", label: "Keyboard shortcuts" },
      { id: "about", label: "About this server" },
      { id: "interface-data", label: "Interface data" },
    ],
  },
];

export const GROUP_LABEL: Record<NavItem["group"], string | null> = {
  top: null,
  setup: "Set up",
  experiments: "Experiments",
  bottom: null,
};
