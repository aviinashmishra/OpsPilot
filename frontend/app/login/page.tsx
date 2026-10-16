"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Eye, EyeOff, ShieldCheck, Sparkles } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { BrandWordmark } from "@/components/layout/brand";
import { ThemeToggle } from "@/components/layout/topbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { InlineError } from "@/components/ui/states";
import { api, errorMessage } from "@/lib/api";
import { useApiHealth, useDemoAccounts } from "@/lib/queries";
import { isSessionValid, useSession } from "@/lib/session";
import type { LoginRequest, TokenResponse } from "@/lib/types";
import { titleCase } from "@/lib/utils";

function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/login")) return "/overview";
  return value;
}

function ApiStatus() {
  const health = useApiHealth();
  if (health.isLoading) return null;
  if (health.isError) {
    return (
      <div className="mt-3 rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-xs text-danger" role="alert">
        <p className="font-medium">The OpsPilot API is not reachable.</p>
        <p className="mt-1 text-danger/90">{errorMessage(health.error)}</p>
        <p className="mt-1 text-fg-muted">
          Start everything with <code className="font-mono">start.cmd</code> in the project folder, or run <code className="font-mono">scripts\doctor.ps1</code> to diagnose. Retrying automatically…
        </p>
      </div>
    );
  }
  if (health.data?.status === "ok") return null;
  return (
    <p className="mt-3 flex items-center gap-1.5 text-[11px] text-warning" role="status">
      <span className="inline-block h-2 w-2 rounded-full bg-warning" aria-hidden />
      The API is running in a degraded state.
    </p>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const reason = searchParams.get("reason");
  const hydrated = useSession((s) => s.hydrated);
  const token = useSession((s) => s.token);
  const expiresAt = useSession((s) => s.expiresAt);
  const setSession = useSession((s) => s.setSession);
  const demo = useDemoAccounts();

  const [tenant, setTenant] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    if (hydrated && isSessionValid({ token, expiresAt })) router.replace(next);
  }, [hydrated, token, expiresAt, router, next]);

  useEffect(() => {
    if (demo.data?.tenant && !tenant) setTenant(demo.data.tenant);
  }, [demo.data, tenant]);

  const login = useMutation({
    mutationFn: (body: LoginRequest) => api<TokenResponse>("/auth/login", { method: "POST", body, auth: false }),
    onSuccess: (response) => {
      setSession(response);
      toast.success(`Welcome back, ${response.user.full_name.split(" ")[0]}`);
      router.replace(next);
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    login.mutate({ tenant: tenant.trim(), email: email.trim(), password });
  };

  const fill = (account: { email: string }) => {
    setTenant(demo.data?.tenant ?? tenant);
    setEmail(account.email);
    if (demo.data?.password) setPassword(demo.data.password);
    else document.getElementById("password")?.focus();
  };

  return (
    <div className="w-full max-w-md">
      <div className="surface-card p-6 sm:p-8">
        <div className="mb-6 flex items-center justify-between">
          <BrandWordmark />
          <ThemeToggle />
        </div>
        <h1 className="text-xl font-semibold">Sign in</h1>
        <ApiStatus />
        {reason === "expired" ? (
          <p className="mt-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning" role="status">
            Your session expired. Please sign in again.
          </p>
        ) : null}
        <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
          <Field label="Tenant" htmlFor="tenant" required>
            <Input id="tenant" value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="acme-demo" autoComplete="organization" required />
          </Field>
          <Field label="Email" htmlFor="email" required>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="username" required />
          </Field>
          <Field label="Password" htmlFor="password" required>
            <div className="relative">
              <Input id="password" type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required className="pr-10" />
              <button type="button" onClick={() => setShowPassword((s) => !s)} className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1.5 text-fg-subtle hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label={showPassword ? "Hide password" : "Show password"}>
                {showPassword ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
              </button>
            </div>
          </Field>
          {login.isError ? <InlineError error={login.error} /> : null}
          <Button type="submit" variant="primary" size="lg" className="w-full" loading={login.isPending} disabled={!tenant || !email || !password} rightIcon={<ArrowRight className="h-4 w-4" aria-hidden />}>
            Sign in
          </Button>
        </form>
      </div>

      {demo.data && demo.data.accounts.length > 0 ? (
        <div className="mt-4 rounded-lg border border-border bg-surface/70 p-4">
          <div className="mb-3 flex items-center gap-2 text-xs font-medium text-fg-muted">
            <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden />
            Demo accounts — click to fill in
          </div>
          <ul className="grid gap-1.5 sm:grid-cols-2">
            {demo.data.accounts.map((account) => (
              <li key={account.email}>
                <button type="button" onClick={() => fill(account)} className="flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-2.5 py-2 text-left text-xs transition-colors hover:border-accent/50 hover:bg-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-fg">{account.name}</span>
                    <span className="block truncate text-fg-subtle">{account.email}</span>
                  </span>
                  <Badge size="sm" tone="accent">
                    {titleCase(account.role)}
                  </Badge>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-10 page-bg">
      <div className="pointer-events-none absolute -left-32 top-10 h-72 w-72 rounded-full bg-accent/20 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -right-24 bottom-0 h-80 w-80 rounded-full bg-accent-2/15 blur-3xl" aria-hidden />
      <div className="relative grid w-full max-w-5xl items-center gap-10 lg:grid-cols-[1.1fr_1fr]">
        <div className="hidden lg:block">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight">
            Your <span className="gradient-text">AI workforce</span>, under control.
          </h2>
          <p className="mt-4 max-w-md text-sm text-fg-muted">
            <ShieldCheck className="mr-1.5 inline h-4 w-4 align-text-bottom text-success" aria-hidden />
            Every consequential action is approved by a person and audited.
          </p>
        </div>
        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>
      </div>
    </div>
  );
}
