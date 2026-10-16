/**
 * Lightweight help metadata, safe to import from always-loaded UI (top bar, command palette).
 * The article bodies live in content.json and are only loaded by the /help pages.
 */
import index from "@/lib/help/index.json";

export interface HelpIndexEntry {
  slug: string;
  title: string;
  group: string;
}

export const HELP_INDEX: HelpIndexEntry[] = index;

/** Dashboard route -> the help article that explains that page. */
const ROUTE_HELP: Array<[prefix: string, slug: string]> = [
  ["/copilot", "copilot"],
  ["/overview", "overview"],
  ["/agents", "agents"],
  ["/workflows", "workflows"],
  ["/approvals", "approvals"],
  ["/tasks", "tasks"],
  ["/analytics", "analytics"],
  ["/audit", "audit-trail"],
  ["/incidents", "incidents"],
  ["/evaluations", "evaluations"],
  ["/system", "scale-and-workers"],
  ["/integrations", "integrations"],
  ["/documents", "documents"],
  ["/admin", "admin"],
];

/** Help link for the page at `pathname`: its article when one exists, otherwise the Help center. */
export function helpHrefFor(pathname: string): string {
  const match = ROUTE_HELP.find(([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  return match ? `/help/${match[1]}` : "/help";
}

/** The dashboard page an article documents, if any (for an "Open this page" button). */
export function pageForArticle(slug: string): string | null {
  return ROUTE_HELP.find(([, s]) => s === slug)?.[0] ?? null;
}
