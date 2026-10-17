"use client";

import { ArrowRight, CheckCircle2, Circle, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { usePermission } from "@/lib/permissions";
import { useOnboarding } from "@/lib/queries";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const storageKey = (tenantId: string) => `opspilot:onboarding-dismissed:${tenantId}`;

/** Self-completing checklist for a new workspace; shown to admins until done or dismissed. */
export function GettingStarted() {
  const canAdmin = usePermission("tenant:admin");
  const tenantId = useSession((s) => s.tenant?.id);
  const onboarding = useOnboarding({ enabled: canAdmin });
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    if (!tenantId) return;
    try {
      setDismissed(window.localStorage.getItem(storageKey(tenantId)) === "1");
    } catch {
      setDismissed(false);
    }
  }, [tenantId]);

  const data = onboarding.data;
  if (!canAdmin || dismissed || !data || data.complete) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      if (tenantId) window.localStorage.setItem(storageKey(tenantId), "1");
    } catch {
      /* storage unavailable: hidden for this visit only */
    }
  };
  const pct = Math.round((data.done / data.total) * 100);
  const aiNote = !data.ai.configured ? "No AI model is configured yet, so agents use their built-in logic." : !data.ai.available ? "The AI model is paused (quota or outage); agents use their built-in logic until it is back." : null;

  return (
    <Card data-testid="getting-started">
      <CardToolbar
        title={`Getting started · ${data.done} of ${data.total}`}
        description={data.sandbox ? "Agents are working on sample data until you connect your systems." : undefined}
        actions={
          <button type="button" onClick={dismiss} className="rounded p-1 text-fg-subtle hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label="Hide getting started">
            <X className="h-4 w-4" aria-hidden />
          </button>
        }
      />
      <CardContent className="space-y-3">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Setup progress">
          <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
        </div>
        <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {data.steps.map((step) => (
            <li key={step.key}>
              <Link
                href={step.href}
                className={cn("group flex h-full items-start gap-2.5 rounded-lg border border-border px-3 py-2.5 transition-colors hover:border-accent/50 hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50", step.done && "opacity-60")}
              >
                {step.done ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-label="Done" /> : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-fg-subtle" aria-label="Not done" />}
                <span className="min-w-0 flex-1">
                  <span className={cn("block text-sm font-medium text-fg", step.done && "line-through decoration-fg-subtle")}>{step.title}</span>
                  <span className="block text-xs text-fg-muted">{step.description}</span>
                </span>
                {!step.done ? <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden /> : null}
              </Link>
            </li>
          ))}
        </ul>
        {aiNote ? <p className="text-xs text-fg-subtle">{aiNote}</p> : null}
      </CardContent>
    </Card>
  );
}
