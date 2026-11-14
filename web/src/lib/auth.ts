import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { getJson, send, SIGNED_OUT } from "@/lib/models";

/** GET /api/auth/status (server/edgebench/api_auth.py): `enabled` is false until the owner sets a password. */
export interface AuthStatus {
  enabled: boolean;
  signed_in: boolean;
}

export const authKey = ["auth"] as const;

export function useAuth() {
  const client = useQueryClient();
  useEffect(() => {
    const again = () => void client.invalidateQueries({ queryKey: authKey });
    window.addEventListener(SIGNED_OUT, again);
    return () => {
      window.removeEventListener(SIGNED_OUT, again);
    };
  }, [client]);
  return useQuery({
    queryKey: authKey,
    queryFn: ({ signal }) => getJson<AuthStatus>("/api/auth/status", signal),
    retry: 1,
  });
}

export const logIn = (password: string) =>
  send<AuthStatus>("POST", "/api/auth/login", { password });
export const logOut = () => send<AuthStatus>("POST", "/api/auth/logout");
