"use client";

import { ArrowLeft, ArrowRight, BookOpen, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import { HelpMarkdown } from "@/components/help/markdown";
import { articleHref } from "@/components/help/parts";
import { ButtonLink } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { type Crumb, PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/states";
import { getArticle, getTrack, groupLabel, neighbours, scrollToHash } from "@/lib/help/content";
import { pageForArticle } from "@/lib/help/routes";
import { ALL_NAV_ITEMS } from "@/lib/constants";
import { useCan } from "@/lib/permissions";

export default function HelpArticlePage({ params }: { params: { slug: string } }) {
  return (
    <Suspense fallback={null}>
      <HelpArticle slug={params.slug} />
    </Suspense>
  );
}

/** Jump to the page the article documents, if the reader may open it. */
function OpenPageButton({ href }: { href: string }) {
  const can = useCan();
  const item = ALL_NAV_ITEMS.find((i) => i.href === href);
  if (!item || (item.permissions && !item.permissions.some((p) => can(p)))) return null;
  return (
    <ButtonLink href={href} variant="outline" size="sm" leftIcon={<ExternalLink className="h-3.5 w-3.5" aria-hidden />}>
      Open {item.label}
    </ButtonLink>
  );
}

function HelpArticle({ slug }: { slug: string }) {
  const params = useSearchParams();
  const article = getArticle(slug);
  const track = getTrack(params?.get("for"));

  useEffect(scrollToHash, [slug]);

  if (!article) {
    return <EmptyState icon={BookOpen} title="This help article does not exist" description="It may have been renamed. Search the help center instead." action={<ButtonLink href="/help">Help center</ButtonLink>} />;
  }

  const parent = article.parent ? getArticle(article.parent) : undefined;
  const crumbs: Crumb[] = [{ label: "Help center", href: "/help" }];
  if (track) crumbs.push({ label: track.title, href: `/help/for/${track.id}` });
  else crumbs.push({ label: groupLabel(article.group), href: `/help#${article.group}` });
  if (parent && !track) crumbs.push({ label: parent.title, href: articleHref(parent.slug) });
  const page = pageForArticle(article.slug);
  // The two shallowest heading levels present: split guide sections start at ####, whole docs at ##.
  const top = Math.min(...article.headings.map((h) => h.level));
  const toc = article.headings.filter((h) => h.level <= top + 1 && h.id !== "in-this-section");
  const { prev, next } = neighbours(article.slug, track);

  return (
    <div className="space-y-5">
      <PageHeader crumbs={crumbs} title={article.title} actions={page ? <OpenPageButton href={page} /> : null} />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_220px]">
        <Card className="min-w-0">
          <CardContent className="max-w-3xl px-5 pb-8 pt-2 sm:px-8">
            <HelpMarkdown body={article.body} headings={article.headings} />
            <p className="mt-10 text-[11px] text-fg-subtle">Source: {article.source}</p>
          </CardContent>
        </Card>

        {toc.length > 1 ? (
          <nav aria-label="On this page" className="sticky top-20 hidden max-h-[calc(100dvh-6rem)] overflow-y-auto xl:block">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-subtle">On this page</p>
            <ul className="space-y-1 border-l border-border text-xs">
              {toc.map((h) => (
                <li key={h.id}>
                  <a href={`#${h.id}`} className={h.level > top ? "block py-0.5 pl-6 text-fg-subtle hover:text-fg" : "block py-0.5 pl-3 text-fg-muted hover:text-fg"}>
                    {h.text}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
      </div>

      {prev || next ? (
        <nav aria-label={track ? `${track.title} reading path` : "More articles"} className="grid gap-3 sm:grid-cols-2">
          {prev ? (
            <Link href={articleHref(prev.slug, track)} className="surface-card group flex items-center gap-3 p-4 hover:border-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
              <ArrowLeft className="h-4 w-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
              <span className="min-w-0">
                <span className="block text-[11px] text-fg-subtle">Previous</span>
                <span className="block truncate text-sm font-medium text-fg group-hover:text-accent">{prev.title}</span>
              </span>
            </Link>
          ) : (
            <span className="hidden sm:block" />
          )}
          {next ? (
            <Link href={articleHref(next.slug, track)} className="surface-card group flex items-center justify-end gap-3 p-4 text-right hover:border-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
              <span className="min-w-0">
                <span className="block text-[11px] text-fg-subtle">Next</span>
                <span className="block truncate text-sm font-medium text-fg group-hover:text-accent">{next.title}</span>
              </span>
              <ArrowRight className="h-4 w-4 shrink-0 text-fg-subtle group-hover:text-accent" aria-hidden />
            </Link>
          ) : null}
        </nav>
      ) : null}
    </div>
  );
}
