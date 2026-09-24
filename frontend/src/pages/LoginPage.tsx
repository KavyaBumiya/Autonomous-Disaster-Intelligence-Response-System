import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { authApi, setAuth } from "@/services/api";
import { Button } from "@/components/ui";

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState("commander@aegis.demo");
  const [password, setPassword] = useState("demo123");
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await authApi.login(username.trim(), password);
      setAuth(res.data.access_token, res.data.role);
      toast.success("Signed in");
      navigate("/dashboard", { replace: true });
    } catch {
      toast.error("Invalid credentials or backend offline");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="ops-shell flex min-h-screen items-center justify-center px-4">
      <form onSubmit={handleSubmit} className="ops-panel w-full max-w-md p-8">
        <div className="mb-6 flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-[#38d9c4] text-lg font-bold text-[#07101c]">
            A
          </span>
          <div>
            <div className="text-lg font-bold tracking-tight">AegisAI</div>
            <div className="ops-kicker">Operator sign-in</div>
          </div>
        </div>

        <label className="ops-stat-label" htmlFor="username">
          Username
        </label>
        <input
          id="username"
          className="ops-input mt-1 mb-4"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />

        <label className="ops-stat-label" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          className="ops-input mt-1 mb-6"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />

        <Button type="submit" variant="primary" block disabled={busy}>
          {busy ? "Signing in…" : "Enter operations center"}
        </Button>

        <p className="mt-4 text-center text-xs leading-5 text-slate-500">
          Demo credentials are pre-filled. All actions require an authenticated operator role.
        </p>
      </form>
    </div>
  );
};
