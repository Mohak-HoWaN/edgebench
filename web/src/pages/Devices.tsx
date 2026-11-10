import { Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useConfirm } from "@/components/ConfirmProvider";
import { EmptyState } from "@/components/EmptyState";
import { Field, NativeSelect } from "@/components/Field";
import { Info } from "@/components/Info";
import { PageHeader, Section } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  guessThisDevice,
  useAddDevice,
  useDevices,
  useReissueToken,
  useRemoveDevice,
  type DeviceInfo,
  type DeviceKind,
  type Enrolment,
} from "@/lib/devices";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND: Record<DeviceKind, string> = { pc: "PC", pi: "Raspberry Pi" };

function command(e: Enrolment): string {
  return `python -m edgebench_agent --server ${e.server_url} --token ${e.enroll_token}`;
}

function EnrolmentPanel({ enrolment }: { enrolment: Enrolment }) {
  const text = command(enrolment);
  return (
    <div className="mt-4 max-w-prose space-y-2 border-l-2 border-primary pl-4 text-sm">
      <p className="font-medium">
        Run this on {enrolment.device.name}, in the folder that holds the agent
      </p>
      <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{text}</pre>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            void navigator.clipboard.writeText(text).then(
              () => {
                toast.success("Command copied");
              },
              () => {
                toast.error("Copying is not allowed here. Select the text instead.");
              },
            );
          }}
        >
          <Copy aria-hidden />
          Copy
        </Button>
        <Info>{`The token works once and expires in ${String(enrolment.expires_minutes)} minutes. The agent needs the agent folder and its Python packages (see agent/README.md). A Raspberry Pi on another network cannot reach this address yet: Pi support comes in a later version.`}</Info>
      </div>
    </div>
  );
}

function Hardware({ fingerprint }: { fingerprint: Record<string, unknown> }) {
  const text = (k: string): string | null => {
    const v = fingerprint[k];
    return typeof v === "string" || typeof v === "number" ? String(v) : null;
  };
  const ram = typeof fingerprint.ram_bytes === "number" ? formatBytes(fingerprint.ram_bytes) : null;
  const packages = fingerprint.packages as Record<string, string> | undefined;
  const rows: [string, string | null][] = [
    ["System", text("os")],
    ["Processor", text("cpu")],
    [
      "Cores",
      [text("physical_cores"), text("logical_cores")].filter(Boolean).join(" physical, ") +
        " logical",
    ],
    ["Memory", ram],
    ["Graphics", text("gpu")],
    ["Python", text("python")],
    ["Raspberry Pi model", text("pi_model")],
  ];
  return (
    <dl className="mt-2 grid max-w-prose grid-cols-[9rem_1fr] gap-y-1 text-sm">
      {rows
        .filter(([, v]) => v)
        .map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="break-words">{v}</dd>
          </div>
        ))}
      {packages && Object.keys(packages).length ? (
        <>
          <dt className="text-muted-foreground">Runtimes</dt>
          <dd className="break-words">
            {Object.entries(packages)
              .map(([k, v]) => `${k} ${v}`)
              .join(", ")}
          </dd>
        </>
      ) : null}
    </dl>
  );
}

function DeviceRow({ d, onToken }: { d: DeviceInfo; onToken: (e: Enrolment) => void }) {
  const confirm = useConfirm();
  const remove = useRemoveDevice();
  const reissue = useReissueToken();
  const mismatch = d.kind !== null && d.expected_kind !== null && d.kind !== d.expected_kind;
  const state = !d.enrolled
    ? "Waiting for its agent to connect"
    : d.running_run !== null
      ? `Running benchmark ${String(d.running_run)}`
      : d.online
        ? "Online"
        : "Offline";
  return (
    <li className="py-4">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="font-medium">{d.name}</span>
        <span className="text-sm text-muted-foreground">
          {d.kind ? KIND[d.kind] : d.expected_kind ? `${KIND[d.expected_kind]} (expected)` : ""}
        </span>
        <span className="flex items-center gap-1.5 text-sm" role="status">
          <span
            aria-hidden
            className={cn(
              "size-2 rounded-full",
              d.online ? "bg-ok" : d.enrolled ? "bg-destructive" : "bg-warn",
            )}
          />
          {state}
        </span>
      </div>
      {mismatch && d.kind && d.expected_kind ? (
        <p className="mt-1 max-w-prose text-sm text-warn">
          You set this up as a {KIND[d.expected_kind]}, but the machine reports itself as a{" "}
          {KIND[d.kind]}. Results are recorded for what the machine reports.
        </p>
      ) : null}
      {d.fingerprint ? <Hardware fingerprint={d.fingerprint} /> : null}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          size="xs"
          variant="outline"
          disabled={reissue.isPending}
          onClick={() => {
            reissue.mutate(d.id, {
              onSuccess: onToken,
              onError: (e) => {
                toast.error(e.message);
              },
            });
          }}
        >
          Connect again
          <span className="sr-only"> {d.name}</span>
        </Button>
        <Button
          size="xs"
          variant="destructive"
          disabled={remove.isPending}
          onClick={() => {
            void confirm({
              title: `Remove ${d.name}?`,
              body: "Its agent is cut off at once and its token stops working. Results it already produced stay.",
              confirmLabel: "Remove device",
              destructive: true,
            }).then((ok) => {
              if (ok) remove.mutate(d.id);
            });
          }}
        >
          Remove
          <span className="sr-only"> {d.name}</span>
        </Button>
      </div>
    </li>
  );
}

export default function Devices() {
  const devices = useDevices();
  const add = useAddDevice();
  const guess = guessThisDevice();
  const [name, setName] = useState(guess.kind === "pi" ? "Raspberry Pi" : "This computer");
  const [kind, setKind] = useState<DeviceKind>(guess.kind);
  const [enrolment, setEnrolment] = useState<Enrolment | null>(null);

  return (
    <>
      <PageHeader
        title="Devices"
        hint="The computers and Raspberry Pis that run your benchmarks. Each runs a small agent that connects to this server."
      />
      <Section title="Add a device" id="add-device">
        <p className="mb-4 max-w-prose text-sm text-muted-foreground">
          This browser looks like it is on a {KIND[guess.kind]} ({guess.reason}). That is only a
          hint: the device's real type is whatever its agent reports.
        </p>
        <form
          className="grid max-w-prose gap-4 sm:grid-cols-[1fr_12rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate(
              { name: name.trim(), expected_kind: kind },
              {
                onSuccess: setEnrolment,
                onError: (err) => {
                  toast.error(err.message);
                },
              },
            );
          }}
        >
          <Field label="Name">
            {(id) => (
              <Input
                id={id}
                value={name}
                maxLength={60}
                onChange={(e) => {
                  setName(e.target.value);
                }}
              />
            )}
          </Field>
          <Field label="Type">
            {(id) => (
              <NativeSelect
                id={id}
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as DeviceKind);
                }}
              >
                <option value="pc">PC</option>
                <option value="pi">Raspberry Pi</option>
              </NativeSelect>
            )}
          </Field>
          <Button type="submit" disabled={!name.trim() || add.isPending}>
            Get a connection command
          </Button>
        </form>
        {enrolment ? <EnrolmentPanel enrolment={enrolment} /> : null}
      </Section>
      <Section title="Your devices" id="your-devices">
        {devices.isPending ? (
          <div aria-busy="true" aria-label="Loading devices">
            <Skeleton className="h-10 w-full max-w-prose" />
          </div>
        ) : devices.isError ? (
          <p className="text-sm">
            The list of devices could not be loaded: {devices.error.message}
          </p>
        ) : devices.data.length === 0 ? (
          <EmptyState title="No devices yet">
            Add this computer above and run the command it gives you. It then appears here with its
            hardware.
          </EmptyState>
        ) : (
          <ul className="divide-y border-y">
            {devices.data.map((d) => (
              <DeviceRow key={d.id} d={d} onToken={setEnrolment} />
            ))}
          </ul>
        )}
      </Section>
    </>
  );
}
