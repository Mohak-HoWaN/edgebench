import { useState, type SyntheticEvent } from "react";
import { Field } from "@/components/Field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { logIn } from "@/lib/auth";

/** Shown instead of the app when the server has an owner password and this browser has no session. */
export function Login() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = (e: SyntheticEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    logIn(password).then(
      () => {
        window.location.reload(); // every query and the live connection start again, now with the cookie
      },
      (err: unknown) => {
        setError(err instanceof Error ? err.message : "Could not sign in.");
        setBusy(false);
      },
    );
  };

  return (
    <main className="grid min-h-dvh place-items-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border p-6">
        <h1 className="text-lg font-semibold">Sign in to EdgeBench</h1>
        <Field label="Owner password">
          {(id) => (
            <Input
              id={id}
              type="password"
              autoComplete="current-password"
              autoFocus
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
              }}
            />
          )}
        </Field>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button type="submit" disabled={busy || password === ""}>
          Sign in
        </Button>
      </form>
    </main>
  );
}
