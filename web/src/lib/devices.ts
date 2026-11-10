import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getJson, send } from "./models";

export type DeviceKind = "pc" | "pi";

export interface DeviceInfo {
  id: number;
  name: string;
  expected_kind: DeviceKind | null;
  /** From the agent's own hardware report, never from the browser. */
  kind: DeviceKind | null;
  enrolled: boolean;
  online: boolean;
  last_seen_at: string | null;
  agent_version: string | null;
  fingerprint: Record<string, unknown> | null;
  running_run: number | null;
  created_at: string;
}

export interface Enrolment {
  device: DeviceInfo;
  enroll_token: string;
  server_url: string;
  expires_minutes: number;
}

export const devicesKey = ["devices"] as const;

/**
 * A guess from the browser, used only to pick a sensible default and the install command. It can be wrong (Windows on
 * ARM, a 32-bit Pi OS), which is why the device's type is always taken from the agent's report.
 */
export function guessThisDevice(): { kind: DeviceKind; reason: string } {
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  const platform = (nav.userAgentData?.platform ?? navigator.platform).toLowerCase();
  const agent = navigator.userAgent.toLowerCase();
  const arm = ["arm", "aarch"].some((s) => platform.includes(s) || agent.includes(s));
  if (platform.includes("linux") && arm) {
    return { kind: "pi", reason: `this browser reports ARM Linux (${platform})` };
  }
  return { kind: "pc", reason: `this browser reports ${platform || "an unknown platform"}` };
}

export function useDevices() {
  return useQuery({
    queryKey: devicesKey,
    queryFn: ({ signal }) => getJson<DeviceInfo[]>("/api/devices", signal),
    refetchInterval: 10_000, // "online" is derived from the last contact, so it ages without any event
  });
}

function useDeviceAction<A, R>(run: (arg: A) => Promise<R>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => queryClient.invalidateQueries({ queryKey: devicesKey }),
  });
}

export const useAddDevice = () =>
  useDeviceAction((a: { name: string; expected_kind: DeviceKind }) =>
    send<Enrolment>("POST", "/api/devices", a),
  );
export const useReissueToken = () =>
  useDeviceAction((id: number) =>
    send<Enrolment>("POST", `/api/devices/${String(id)}/enroll-token`),
  );
export const useRemoveDevice = () =>
  useDeviceAction((id: number) => send("DELETE", `/api/devices/${String(id)}`));

/** How many threads a device reports, from its hardware fingerprint (it can be missing). */
export function cpuLimits(fingerprint: Record<string, unknown> | null): {
  logical: number;
  physical: number;
} {
  const num = (k: string) => {
    const v = fingerprint?.[k];
    return typeof v === "number" && v > 0 ? v : 0;
  };
  return { logical: num("logical_cores"), physical: num("physical_cores") };
}

/** "0-3,8" to [0, 1, 2, 3, 8], checked against the CPUs the device has (`logical` 0 means unknown, so any number passes). */
export function parseCpuList(
  text: string,
  logical: number,
): { cpus: number[] | null; error: string | null } {
  const parts = text
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length === 0)
    return { cpus: null, error: "Write at least one CPU number, for example 0-3." };
  const cpus: number[] = [];
  for (const part of parts) {
    const m = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!m) return { cpus: null, error: `"${part}" is not a CPU number or a range like 0-3.` };
    const from = Number(m[1]);
    const to = m[2] === undefined ? from : Number(m[2]);
    if (to < from) return { cpus: null, error: `"${part}" counts backwards.` };
    for (let c = from; c <= to; c++) cpus.push(c);
  }
  const unique = [...new Set(cpus)];
  if (unique.length !== cpus.length)
    return { cpus: null, error: "The list names the same CPU twice." };
  const outside = unique.find((c) => logical > 0 && c >= logical);
  if (outside !== undefined) {
    return {
      cpus: null,
      error: `CPU ${String(outside)} does not exist: this device has CPUs 0 to ${String(logical - 1)}.`,
    };
  }
  return { cpus: unique, error: null };
}
