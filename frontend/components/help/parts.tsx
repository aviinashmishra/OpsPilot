"use client";

import { Briefcase, ChevronRight, Code2, type LucideIcon, Settings, Users } from "lucide-react";
import Link from "next/link";
import { Fragment } from "react";

import { groupLabel, type HelpArticle, type HelpHit, type HelpTrack, searchTerms } from "@/lib/help/content";
import { cn } from "@/lib/utils";

export const TRACK_ICONS: Record<string, LucideIcon> = { users: Users, settings: Settings, code: Code2, briefcase: Briefcase };

export function articleHref(slug: string, track?: HelpTrack | null, hash?: string): string {
  return `/help/${slug}${track ? `?for=${track.id}` : ""}${hash ? `#${hash}` : ""}`;
}

/** Wraps every search term in <mark>. */
export function Highlight({ text, query }: { text: string; query: string }) {
  const terms = searchTerms(query).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return <>{text}</>;
  const parts = text.split(new RegExp(`(${terms.join("|")})`, "gi"));
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded-sm bg-accent/20 px-0.5 text-fg">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

export function ArticleRow({ article, href, index, className, hideSummary }: { article: HelpArticle; href: string; index?: number; className?: string; hideSummary?: boolean }) {
  return (
    <Link href={href} className={cn("group flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50", className)}>
      {index !== undefined ? <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-3 text-[11px] font-semibold text-fg-muted group-hover:bg-accent/15 group-hover:text-accent">{index}</span> : null}
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-fg group-hover:text-accent">{article.title}</span>
        {article.summary && !hideSummary ? <span className="mt-0.5 line-clamp-2 block text-xs leading-5 text-fg-muted">{article.summary}</span> : null}
      </span>
      <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-fg-subtle transition-transform group-hover:translate-x-0.5 group-hover:text-accent" aria-hidden />
    </Link>
  );
}

export function SearchResults({ hits, query }: { hits: HelpHit[]; query: string }) {
  if (!hits.length) {
    return <p className="px-1 py-8 text-center text-sm text-fg-muted">No articles match “{query}”. Try fewer or different words.</p>;
  }
  return (
    <ol className="space-y-1" data-testid="help-search-results" aria-label="Search results">
      {hits.map(({ article, snippet, heading }) => (
        <li key={article.slug}>
          <Link href={articleHref(article.slug, null, heading?.id)} className="group block rounded-lg px-3 py-3 transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
            <span className="flex flex-wrap items-baseline gap-x-2">
              <span className="text-sm font-medium text-fg group-hover:text-accent">
                <Highlight text={article.title} query={query} />
              </span>
              <span className="text-[11px] text-fg-subtle">
                {groupLabel(article.group)}
                {heading ? ` › ${heading.text}` : ""}
              </span>
            </span>
            <span className="mt-1 line-clamp-2 block text-xs leading-5 text-fg-muted">
              <Highlight text={snippet} query={query} />
            </span>
          </Link>
        </li>
      ))}
    </ol>
  );
}
