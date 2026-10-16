"use client";

import { Search, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ArticleRow, SearchResults, TRACK_ICONS, articleHref } from "@/components/help/parts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { HELP_ARTICLES, HELP_GROUPS, HELP_TRACKS, type HelpAudience, readAudience, scrollToHash, searchHelp, trackArticles, trackForRoles } from "@/lib/help/content";
import { useDebounced } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

export default function HelpPage() {
  return (
    <Suspense fallback={null}>
      <HelpHome />
    </Suspense>
  );
}

function HelpHome() {
  const router = useRouter();
  const params = useSearchParams();
  const [query, setQuery] = useState(() => params?.get("q") ?? "");
  const q = useDebounced(query.trim(), 150);
  const hits = useMemo(() => searchHelp(q), [q]);
  const roles = useSession((s) => s.user?.roles);
  const forRole = trackForRoles(roles);
  const [remembered, setRemembered] = useState<HelpAudience | null>(null);

  useEffect(() => {
    setRemembered(readAudience());
    scrollToHash();
  }, []);
  const urlQuery = params?.get("q") ?? "";
  useEffect(() => {
    // Keep ?q= shareable; only touch the URL when the search changes (so /help#group links keep their hash).
    if (q !== urlQuery) router.replace(q ? `/help?q=${encodeURIComponent(q)}` : "/help", { scroll: false });
  }, [q, urlQuery, router]);

  return (
    <div className="space-y-6">
      <PageHeader title="Help center" />

      <div className="relative max-w-2xl">
        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search the help: “approve a purchase order”, “GEMINI_API_KEY”, “audit chain”…"
          aria-label="Search the help center"
          data-testid="help-search"
          className="h-12 w-full rounded-lg border border-border bg-surface pl-10 pr-10 text-sm text-fg shadow-soft outline-none transition-colors placeholder:text-fg-subtle hover:border-border-strong focus-visible:border-accent/60 focus-visible:ring-2 focus-visible:ring-ring/40 [&::-webkit-search-cancel-button]:hidden"
          autoFocus
        />
        {query ? (
          <button type="button" onClick={() => setQuery("")} className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-fg-subtle hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label="Clear search">
            <X className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
      </div>

      {q ? (
        <Card>
          <CardContent className="pt-3">
            <p className="px-3 pb-2 text-xs text-fg-subtle" aria-live="polite">
              {hits.length === 0 ? "No results" : `${hits.length}${hits.length === 25 ? "+" : ""} result${hits.length === 1 ? "" : "s"}`}
            </p>
            <SearchResults hits={hits} query={q} />
          </CardContent>
        </Card>
      ) : (
        <>
          <section aria-labelledby="help-audiences" className="space-y-3">
            <h2 id="help-audiences" className="text-sm font-semibold text-fg">
              Start with your role
            </h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="help-tracks">
              {HELP_TRACKS.map((track) => {
                const Icon = TRACK_ICONS[track.icon] ?? Search;
                const mine = forRole?.id === track.id;
                const last = !mine && remembered === track.id;
                return (
                  <Link
                    key={track.id}
                    href={`/help/for/${track.id}`}
                    className={cn("surface-card group flex flex-col gap-3 p-5 transition-[border-color,box-shadow] hover:border-accent/50 hover:shadow-glow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50", mine && "border-accent/40")}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent/12 text-accent">
                        <Icon className="h-[18px] w-[18px]" aria-hidden />
                      </span>
                      {mine ? (
                        <Badge size="sm" tone="accent">
                          Your role
                        </Badge>
                      ) : last ? (
                        <Badge size="sm">Last opened</Badge>
                      ) : null}
                    </span>
                    <span>
                      <span className="block text-sm font-semibold text-fg group-hover:text-accent">{track.title}</span>
                      <span className="mt-1 block text-xs leading-5 text-fg-muted">{track.who}</span>
                    </span>
                    <span className="mt-auto text-[11px] text-fg-subtle">
                      {trackArticles(track).length} articles · {track.steps.length} steps
                    </span>
                  </Link>
                );
              })}
            </div>
          </section>

          <section aria-labelledby="help-browse" className="space-y-3">
            <h2 id="help-browse" className="text-sm font-semibold text-fg">
              Browse all topics
            </h2>
            <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
              {HELP_GROUPS.map((group) => {
                const articles = HELP_ARTICLES.filter((a) => a.group === group.id && !a.parent);
                const children = HELP_ARTICLES.filter((a) => a.group === group.id && a.parent);
                if (!articles.length) return null;
                return (
                  <Card key={group.id} id={group.id} className="scroll-mt-20">
                    <CardHeader className="pb-1">
                      <CardTitle>{group.label}</CardTitle>
                    </CardHeader>
                    <CardContent className="px-2 pb-3">
                      {articles.map((article) => {
                        const sub = children.filter((c) => c.parent === article.slug);
                        return (
                          <div key={article.slug}>
                            {/* A section overview lists its parts as links below, so its summary would only repeat them. */}
                            <ArticleRow article={article} href={articleHref(article.slug)} className="py-2" hideSummary={sub.length > 0} />
                            {sub.length ? (
                              <ul className="mb-1 ml-6 flex flex-wrap gap-x-3 gap-y-1 border-l border-border pl-3">
                                {sub.map((c) => (
                                  <li key={c.slug}>
                                    <Link href={articleHref(c.slug)} className="text-xs text-fg-muted hover:text-accent focus-visible:outline-none focus-visible:underline">
                                      {c.title}
                                    </Link>
                                  </li>
                                ))}
                              </ul>
                            ) : null}
                          </div>
                        );
                      })}
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
