"use client";

import { BookOpen } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { ArticleRow, TRACK_ICONS, articleHref } from "@/components/help/parts";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/states";
import { HELP_TRACKS, getArticle, getTrack, rememberAudience } from "@/lib/help/content";

export default function HelpTrackPage({ params }: { params: { audience: string } }) {
  const track = getTrack(params.audience);

  useEffect(() => {
    if (track) rememberAudience(track.id);
  }, [track]);

  if (!track) {
    return <EmptyState icon={BookOpen} title="This reading path does not exist" action={<ButtonLink href="/help">Help center</ButtonLink>} />;
  }

  const Icon = TRACK_ICONS[track.icon] ?? BookOpen;
  let n = 0;

  return (
    <div className="space-y-6">
      <PageHeader
        crumbs={[{ label: "Help center", href: "/help" }, { label: track.title }]}
        title={
          <span className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/12 text-accent">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            {track.title}
          </span>
        }
      />
      <p className="-mt-3 max-w-2xl text-sm text-fg-muted">{track.who}</p>

      <div className="grid gap-4 lg:grid-cols-2" data-testid="help-track-steps">
        {track.steps.map((step, i) => (
          <Card key={step.title}>
            <CardHeader className="pb-1">
              <CardTitle className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-[0.14em] text-accent">Step {i + 1}</span>
                <span>{step.title}</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="px-2 pb-3">
              {step.articles.map((slug) => {
                const article = getArticle(slug);
                return article ? <ArticleRow key={slug} article={article} href={articleHref(slug, track)} index={++n} /> : null;
              })}
            </CardContent>
          </Card>
        ))}
      </div>

      <nav aria-label="Other reading paths" className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
        <span>Other roles:</span>
        {HELP_TRACKS.filter((t) => t.id !== track.id).map((t) => (
          <Link key={t.id} href={`/help/for/${t.id}`} className="rounded-full border border-border px-2.5 py-1 hover:border-accent/50 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
            {t.title}
          </Link>
        ))}
      </nav>
    </div>
  );
}
