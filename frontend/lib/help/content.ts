/**
 * Help center content: articles generated from the repository docs by scripts/build-help.mjs,
 * plus the hand-curated audience tracks in tracks.json. Import only from /help pages.
 */
import content from "@/lib/help/content.json";
import tracks from "@/lib/help/tracks.json";

export interface HelpHeading {
  id: string;
  text: string;
  level: number;
}

export interface HelpArticle {
  slug: string;
  title: string;
  group: string;
  source: string;
  parent?: string;
  summary: string;
  headings: HelpHeading[];
  body: string;
}

export interface HelpGroup {
  id: string;
  label: string;
}

export type HelpAudience = "business" | "admins" | "developers" | "executives";

export interface HelpTrack {
  id: HelpAudience;
  title: string;
  who: string;
  roles: string[];
  icon: string;
  steps: Array<{ title: string; articles: string[] }>;
}

export const HELP_GROUPS: HelpGroup[] = content.groups;
export const HELP_ARTICLES: HelpArticle[] = content.articles;
export const HELP_TRACKS = tracks as HelpTrack[];

const BY_SLUG = new Map(HELP_ARTICLES.map((a) => [a.slug, a]));

export function getArticle(slug: string): HelpArticle | undefined {
  return BY_SLUG.get(slug);
}

export function getTrack(id: string | null | undefined): HelpTrack | undefined {
  return HELP_TRACKS.find((t) => t.id === id);
}

export function groupLabel(id: string): string {
  return HELP_GROUPS.find((g) => g.id === id)?.label ?? id;
}

/** The track whose audience matches one of the user's roles (admins first), if any. */
export function trackForRoles(roles: readonly string[] | undefined): HelpTrack | undefined {
  if (!roles?.length) return undefined;
  return HELP_TRACKS.find((t) => t.id === "admins" && t.roles.some((r) => roles.includes(r))) ?? HELP_TRACKS.find((t) => t.roles.some((r) => roles.includes(r)));
}

/** Articles of a track in reading order (an article listed twice keeps its first position). */
export function trackArticles(track: HelpTrack): HelpArticle[] {
  const slugs = [...new Set(track.steps.flatMap((s) => s.articles))];
  return slugs.map((s) => BY_SLUG.get(s)).filter((a): a is HelpArticle => Boolean(a));
}

/** Previous/next article: within the reader's track when given, otherwise in document order. */
export function neighbours(slug: string, track?: HelpTrack): { prev?: HelpArticle; next?: HelpArticle } {
  const list = track ? trackArticles(track) : HELP_ARTICLES;
  const i = list.findIndex((a) => a.slug === slug);
  if (i < 0) return {};
  return { prev: list[i - 1], next: list[i + 1] };
}

// --- search -------------------------------------------------------------------------------------------

const plainCache = new Map<string, string>();

function plainText(article: HelpArticle): string {
  let text = plainCache.get(article.slug);
  if (text === undefined) {
    text = article.body
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/^#{1,6}\s+/gm, "")
      .replace(/^\s*\|?\s*:?-{3,}.*$/gm, " ")
      .replace(/[`*]/g, "")
      .replace(/[>|#]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    plainCache.set(article.slug, text);
  }
  return text;
}

export interface HelpHit {
  article: HelpArticle;
  score: number;
  snippet: string;
  /** Best heading to jump to, when the match is inside a section. */
  heading?: HelpHeading;
}

export function searchTerms(query: string): string[] {
  return [...new Set(query.toLowerCase().split(/[^\p{L}\p{N}_.:-]+/u).filter((t) => t.length > 1))];
}

function count(haystack: string, needle: string, cap: number): number {
  let n = 0;
  for (let i = haystack.indexOf(needle); i >= 0 && n < cap; i = haystack.indexOf(needle, i + needle.length)) n++;
  return n;
}

/** Ranked full-text search: every term must appear; title > headings > summary > body. */
export function searchHelp(query: string, limit = 25): HelpHit[] {
  const terms = searchTerms(query);
  if (!terms.length) return [];
  const phrase = query.trim().toLowerCase();
  const hits: HelpHit[] = [];
  for (const article of HELP_ARTICLES) {
    const title = article.title.toLowerCase();
    const headings = article.headings.map((h) => h.text.toLowerCase());
    const summary = article.summary.toLowerCase();
    const text = plainText(article);
    const lower = text.toLowerCase();
    let score = 0;
    let all = true;
    for (const term of terms) {
      const inTitle = title.includes(term);
      const inHeadings = headings.filter((h) => h.includes(term)).length;
      const inBody = count(lower, term, 8);
      if (!inTitle && !inHeadings && !inBody) {
        all = false;
        break;
      }
      score += (inTitle ? 12 : 0) + Math.min(inHeadings, 3) * 4 + (summary.includes(term) ? 3 : 0) + inBody;
    }
    if (!all) continue;
    if (title.includes(phrase)) score += 20;
    else if (lower.includes(phrase)) score += 6;
    if (terms.length > 1 && lower.includes(terms.join("_"))) score += 10; // "gemini api key" finds GEMINI_API_KEY
    const heading = article.headings.find((h) => terms.some((t) => h.text.toLowerCase().includes(t)));
    const at = [phrase, ...terms].map((t) => lower.indexOf(t)).find((i) => i >= 0) ?? 0;
    const start = Math.max(0, at - 70);
    const snippet = `${start > 0 ? "…" : ""}${text.slice(start, start + 200).trim()}${start + 200 < text.length ? "…" : ""}`;
    hits.push({ article, score, snippet, heading });
  }
  return hits.sort((a, b) => b.score - a.score || a.article.title.localeCompare(b.article.title)).slice(0, limit);
}

/**
 * Scroll to the URL's #section once the content exists. Help pages render after the auth check,
 * so the browser's own hash scroll on a full page load fires before the target element is there.
 */
export function scrollToHash(): void {
  const id = decodeURIComponent(window.location.hash.slice(1));
  if (id) document.getElementById(id)?.scrollIntoView();
}

// --- remembered audience (per-browser convenience only) -----------------------------------------

const AUDIENCE_KEY = "opspilot.help.audience";

export function readAudience(): HelpAudience | null {
  try {
    const v = window.localStorage.getItem(AUDIENCE_KEY);
    return getTrack(v) ? (v as HelpAudience) : null;
  } catch {
    return null;
  }
}

export function rememberAudience(id: HelpAudience): void {
  try {
    window.localStorage.setItem(AUDIENCE_KEY, id);
  } catch {
    // storage unavailable (private mode): the choice simply isn't remembered
  }
}
