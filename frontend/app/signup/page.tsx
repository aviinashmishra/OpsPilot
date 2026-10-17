"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Eye, EyeOff, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { BrandWordmark } from "@/components/layout/brand";
import { ThemeToggle } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { InlineError } from "@/components/ui/states";
import { Switch } from "@/components/ui/switch";
import { api, ApiError } from "@/lib/api";
import { useApiHealth } from "@/lib/queries";
import { isSessionValid, useSession } from "@/lib/session";
import type { SignupRequest, TokenResponse } from "@/lib/types";

const MIN_PASSWORD = 10;

function passwordProblem(password: string): string | null {
  if (!password) return null;
  if (password.length < MIN_PASSWORD) return `At least ${MIN_PASSWORD} characters`;
  if (/^\d+$/.test(password) || /^[A-Za-z]+$/.test(password)) return "Mix letters with numbers or symbols";
  return null;
}

export default function SignupPage() {
  const router = useRouter();
  const health = useApiHealth();
  const hydrated = useSession((s) => s.hydrated);
  const token = useSession((s) => s.token);
  const expiresAt = useSession((s) => s.expiresAt);
  const setSession = useSession((s) => s.setSession);

  const [form, setForm] = useState({ company: "", full_name: "", email: "", password: "" });
  const [sampleData, setSampleData] = useState(true);
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    if (hydrated && isSessionValid({ token, expiresAt })) router.replace("/overview");
  }, [hydrated, token, expiresAt, router]);

  const signup = useMutation({
    mutationFn: (body: SignupRequest) => api<TokenResponse>("/auth/signup", { method: "POST", body, auth: false }),
    onSuccess: (response) => {
      setSession(response);
      toast.success(`Welcome to OpsPilot, ${response.user.full_name.split(" ")[0]}`, { description: `Workspace ${response.tenant.slug} is ready.` });
      router.replace("/overview");
    },
  });

  const fieldError = (field: string) => (signup.error instanceof ApiError && signup.error.details?.field === field ? signup.error.message : null);
  const weak = passwordProblem(form.password);
  const ready = form.company.trim().length >= 2 && form.full_name.trim() && /\S+@\S+\.\S+/.test(form.email) && form.password && !weak;
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    signup.mutate({ company: form.company.trim(), full_name: form.full_name.trim(), email: form.email.trim(), password: form.password, sample_data: sampleData });
  };

  const disabled = health.data && health.data.signup_enabled === false;

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden px-4 py-10 page-bg">
      <div className="pointer-events-none absolute -left-32 top-10 h-72 w-72 rounded-full bg-accent/20 blur-3xl" aria-hidden />
      <div className="pointer-events-none absolute -right-24 bottom-0 h-80 w-80 rounded-full bg-accent-2/15 blur-3xl" aria-hidden />
      <div className="relative grid w-full max-w-5xl items-center gap-10 lg:grid-cols-[1.1fr_1fr]">
        <div className="hidden lg:block">
          <h2 className="text-4xl font-semibold leading-tight tracking-tight">
            Your <span className="gradient-text">AI workforce</span>, ready in a minute.
          </h2>
          <p className="mt-4 max-w-md text-sm text-fg-muted">
            <ShieldCheck className="mr-1.5 inline h-4 w-4 align-text-bottom text-success" aria-hidden />
            25 agents start on safe sample data. Connect your real systems whenever you are ready.
          </p>
        </div>
        <div className="w-full max-w-md">
          <div className="surface-card p-6 sm:p-8">
            <div className="mb-6 flex items-center justify-between">
              <BrandWordmark />
              <ThemeToggle />
            </div>
            <h1 className="text-xl font-semibold">Create your workspace</h1>
            {disabled ? (
              <p className="mt-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning" role="status">
                Sign-up is turned off on this installation. Ask your administrator for an account.
              </p>
            ) : null}
            <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
              <Field label="Company" htmlFor="company" required error={fieldError("company")}>
                <Input id="company" value={form.company} onChange={set("company")} placeholder="Northwind Traders" autoComplete="organization" required />
              </Field>
              <Field label="Your name" htmlFor="full_name" required error={fieldError("full_name")}>
                <Input id="full_name" value={form.full_name} onChange={set("full_name")} placeholder="Nora North" autoComplete="name" required />
              </Field>
              <Field label="Work email" htmlFor="email" required error={fieldError("email")}>
                <Input id="email" type="email" value={form.email} onChange={set("email")} placeholder="you@company.com" autoComplete="email" required />
              </Field>
              <Field label="Password" htmlFor="password" required hint={weak ?? `${MIN_PASSWORD}+ characters, letters and numbers`} error={fieldError("password")}>
                <div className="relative">
                  <Input id="password" type={showPassword ? "text" : "password"} value={form.password} onChange={set("password")} autoComplete="new-password" required className="pr-10" />
                  <button type="button" onClick={() => setShowPassword((s) => !s)} className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1.5 text-fg-subtle hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label={showPassword ? "Hide password" : "Show password"}>
                    {showPassword ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
                  </button>
                </div>
              </Field>
              <label className="flex items-start justify-between gap-3 rounded-md border border-border bg-surface-2/50 px-3 py-2.5">
                <span>
                  <span className="block text-sm font-medium text-fg">Start with sample data</span>
                  <span className="block text-xs text-fg-muted">Recommended. Every agent works immediately.</span>
                </span>
                <Switch checked={sampleData} onCheckedChange={setSampleData} aria-label="Start with sample data" />
              </label>
              {signup.isError && !["company", "full_name", "email", "password"].some((f) => fieldError(f)) ? <InlineError error={signup.error} /> : null}
              <Button type="submit" variant="primary" size="lg" className="w-full" loading={signup.isPending} disabled={!ready || Boolean(disabled)} rightIcon={<ArrowRight className="h-4 w-4" aria-hidden />}>
                Create workspace
              </Button>
            </form>
            <p className="mt-5 border-t border-border pt-4 text-center text-sm text-fg-muted">
              Already have an account?{" "}
              <Link href="/login" className="font-medium text-accent hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
