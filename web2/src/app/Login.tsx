import { useMutation } from "@tanstack/react-query";
import { Eye, EyeOff, Zap } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Button, Input, Problem } from "../components/ui";

export function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const login = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/login", { body: { password } })),
    onSuccess: onDone,
  });
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <form
        className="w-full max-w-sm space-y-5 rounded-xl border border-line bg-surface p-7 shadow-sm"
        onSubmit={(event) => {
          event.preventDefault();
          login.mutate();
        }}
      >
        <div className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-on-primary">
            <Zap size={18} aria-hidden />
          </span>
          <span className="text-xl font-bold tracking-tight">Outbound</span>
        </div>
        <div>
          <h1 className="text-lg font-semibold">Sign in</h1>
          <p className="text-xs text-muted">Use the operator password set for this server.</p>
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-xs font-medium">
            Password
          </label>
          <div className="relative">
            <Input id="password" type={shown ? "text" : "password"} autoFocus autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="h-9 pr-9" />
            <button type="button" aria-label={shown ? "Hide password" : "Show password"} onClick={() => setShown(!shown)} className="absolute right-2 top-2 text-muted hover:text-ink">
              {shown ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <Problem error={login.error} />
        <Button type="submit" busy={login.isPending} disabled={!password} className="h-9 w-full">
          Sign in
        </Button>
        <p className="text-center text-[11px] text-muted">Five wrong tries in a minute pause sign-in for a minute. Sessions last 12 hours.</p>
      </form>
    </main>
  );
}
