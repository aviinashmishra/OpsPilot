#!/usr/bin/env node
/**
 * Builds the in-app Help center content from the repository docs.
 *
 *   docs/*.md, README.md, .env.example, frontend/.env.local.example
 *     -> frontend/lib/help/content.json  (articles: markdown body, headings, search text)
 *     -> frontend/lib/help/index.json    (slug/title/group only, for the command palette)
 *
 * Runs before `next build` / `next dev`. Deploy builds rooted at frontend/ (Render, Vercel,
 * Docker) have no ../docs, so the script then keeps the committed JSON and exits 0.
 * Output is deterministic (no timestamps): regenerating without doc changes is a no-op.
 * `--check` fails if the committed JSON is stale (for CI).
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ROOT = path.resolve(FRONTEND, "..");
const OUT_DIR = path.join(FRONTEND, "lib", "help");
const CHECK = process.argv.includes("--check");

const GROUPS = [
  { id: "start", label: "Getting started" },
  { id: "pages", label: "Using each page" },
  { id: "guides", label: "How-to guides" },
  { id: "reference", label: "Reference" },
  { id: "support", label: "Troubleshooting" },
  { id: "value", label: "Value & governance" },
  { id: "technical", label: "Technical & setup" },
];

/** USER_GUIDE "## N." sections: their group, and which are split into one article per "###". */
const GUIDE_GROUP = { 1: "start", 2: "start", 3: "start", 4: "pages", 5: "reference", 6: "reference", 7: "reference", 8: "guides", 9: "guides", 10: "support", 11: "reference" };
const GUIDE_SPLIT = new Set([2, 4, 9]);

const WHOLE_DOCS = [
  { file: "docs/KPI_AND_ROI.md", slug: "kpi-and-roi", title: "KPIs and ROI", group: "value" },
  { file: "docs/LIMITATIONS.md", slug: "limitations", title: "Known limitations", group: "value" },
  { file: "docs/DEPLOYMENT.md", slug: "deployment", title: "Deployment guide", group: "technical" },
  { file: "docs/ARCHITECTURE.md", slug: "architecture", title: "Architecture", group: "technical" },
  { file: "docs/API.md", slug: "api-reference", title: "API reference", group: "technical" },
  { file: "docs/THREAT_MODEL.md", slug: "security-threat-model", title: "Security threat model", group: "technical" },
  { file: "README.md", slug: "project-readme", title: "Project README", group: "technical" },
];

// --- markdown helpers ------------------------------------------------------------------------

function plainInline(text) {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[`*_~]/g, "")
    .replace(/<[^>]+>/g, "")
    .trim();
}

/** GitHub's heading anchor algorithm, with per-document de-duplication ("x", "x-1", ...). */
function githubSlug(text, seen) {
  let slug = plainInline(text).toLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu, "").replace(/\s/g, "-");
  if (seen) {
    const n = seen.get(slug) ?? 0;
    seen.set(slug, n + 1);
    if (n > 0) slug = `${slug}-${n}`;
  }
  return slug;
}

function titleFromHeading(text) {
  return plainInline(text).replace(/^\d+(\.\d+)*\.?\s+/, "").replace(/^Recipe \d+:\s*/, "");
}

/** Lines of a markdown text, headings tagged with level/text/anchor (fenced code is never a heading). */
function scan(markdown, seen = new Map()) {
  let fence = null;
  return markdown
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => {
      const f = line.match(/^\s*(```|~~~)/);
      if (f) {
        if (!fence) fence = f[1];
        else if (line.trim().startsWith(fence)) fence = null;
        return { line, level: 0 };
      }
      if (fence) return { line, level: 0 };
      const h = line.match(/^(#{1,6})\s+(.*?)\s*#*\s*$/);
      return h ? { line, level: h[1].length, text: h[2], anchor: githubSlug(h[2], seen) } : { line, level: 0 };
    });
}

function toPlainText(markdown) {
  return markdown
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```\w*/g, " "))
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/^\s*\|?\s*:?-{3,}.*$/gm, " ")
    .replace(/[`*]/g, "") // inline markers vanish ("**roles**." -> "roles."); "_" stays (GEMINI_API_KEY)
    .replace(/[>|]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function summaryOf(body) {
  const paragraph = body
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .find((p) => p && !/^(#|\||```|---|[-*]\s|\d+\.\s|<)/.test(p));
  const text = paragraph ? toPlainText(paragraph) : "";
  return text.length > 200 ? `${text.slice(0, 197).replace(/\s+\S*$/, "")}…` : text;
}

// --- article building ------------------------------------------------------------------------

const articles = [];
/** "docs/FILE.md" or "docs/FILE.md#anchor" -> in-app href. */
const linkMap = new Map();

/** rows: scanned lines (headings keep their source-document anchors, so in-page links stay valid). */
function addArticle({ slug, title, group, source, docKey, rows, parent }) {
  if (articles.some((a) => a.slug === slug)) throw new Error(`Duplicate help slug "${slug}" (${source})`);
  for (const r of rows) if (r.level && r.anchor) linkMap.set(`${docKey}#${r.anchor}`, `/help/${slug}#${r.anchor}`);
  while (rows.length && !rows[0].line.trim()) rows.shift();
  articles.push({ slug, title, group, source, docKey, rows, parent });
}

const lineRows = (lines) => lines.map((line) => ({ line, level: 0 }));

function buildGuide(file) {
  const rows = scan(readFileSync(path.join(ROOT, file), "utf8"));
  linkMap.set(file, "/help");
  const sections = [];
  for (const r of rows) {
    if (r.level === 2) sections.push({ head: r, rows: [] });
    else if (sections.length && r.line.trim() !== "---") sections[sections.length - 1].rows.push(r);
  }
  for (const section of sections) {
    if (/^contents$/i.test(plainInline(section.head.text))) continue; // the hand-written TOC
    const num = Number((section.head.text.match(/^(\d+)\./) ?? [])[1]);
    const group = GUIDE_GROUP[num] ?? "technical";
    const title = titleFromHeading(section.head.text);
    const slug = githubSlug(title);
    const ref = num ? `User guide §${num}` : "User guide appendix";
    if (!GUIDE_SPLIT.has(num)) {
      addArticle({ slug, title, group, source: ref, docKey: file, rows: section.rows });
      linkMap.set(`${file}#${section.head.anchor}`, `/help/${slug}`);
      continue;
    }
    const intro = [];
    const children = [];
    for (const r of section.rows) {
      if (r.level === 3) children.push({ head: r, rows: [] });
      else (children.length ? children[children.length - 1].rows : intro).push(r);
    }
    const childList = children.map((c) => {
      const t = titleFromHeading(c.head.text);
      return { line: `- [${t}](/help/${githubSlug(t)})`, level: 0 };
    });
    addArticle({ slug, title, group, source: ref, docKey: file, rows: [...intro, { line: "", level: 0 }, { line: "### In this section", level: 3, text: "In this section", anchor: "in-this-section" }, { line: "", level: 0 }, ...childList] });
    linkMap.set(`${file}#${section.head.anchor}`, `/help/${slug}`);
    for (const child of children) {
      const childTitle = titleFromHeading(child.head.text);
      const childSlug = githubSlug(childTitle);
      const sub = (child.head.text.match(/^(\d+\.\d+)/) ?? [])[1];
      addArticle({ slug: childSlug, title: childTitle, group, source: sub ? `User guide §${sub}` : ref, docKey: file, rows: child.rows, parent: slug });
      linkMap.set(`${file}#${child.head.anchor}`, `/help/${childSlug}`);
    }
  }
}

function buildWholeDoc({ file, slug, title, group }) {
  const rows = scan(readFileSync(path.join(ROOT, file), "utf8"));
  const h1 = rows.findIndex((r) => r.level === 1);
  addArticle({ slug, title, group, source: file, docKey: file, rows: rows.filter((_, i) => i !== h1) });
  if (h1 >= 0) linkMap.set(`${file}#${rows[h1].anchor}`, `/help/${slug}`);
  linkMap.set(file, `/help/${slug}`);
}

// --- configuration reference (generated from the env templates) --------------------------------

function parseEnvTemplate(file) {
  const sections = [];
  const vars = new Map();
  let current = null;
  let pending = [];
  let last = null;
  for (const raw of readFileSync(path.join(ROOT, file), "utf8").replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const header = line.match(/^# -{2,}\s*(.+?)\s*-{2,}$/);
    if (header) {
      current = { title: header[1], vars: [] };
      sections.push(current);
      pending = [];
      last = null;
      continue;
    }
    const v = line.match(/^(# )?([A-Z][A-Z0-9_]+)=(.*)$/);
    if (v) {
      if (!current) {
        current = { title: "Settings", vars: [] };
        sections.push(current);
      }
      const [value, ...comment] = v[3].split(/\s+#\s+/);
      const key = `${current.title}:${v[2]}`;
      let entry = vars.get(key);
      if (!entry) {
        entry = { name: v[2], active: null, examples: [], notes: [] };
        vars.set(key, entry);
        current.vars.push(entry);
      }
      const val = value.trim();
      if (!v[1] && entry.active === null) entry.active = val;
      else if (val && val !== entry.active && !entry.examples.includes(val)) entry.examples.push(val);
      for (const note of [...pending, comment.join(" # ")].map((n) => n.trim()).filter(Boolean)) if (!entry.notes.includes(note)) entry.notes.push(note);
      pending = [];
      last = entry;
      continue;
    }
    const continuation = line.match(/^#\s{2,}(.+)$/); // indented comment: belongs to the variable above
    if (continuation && last) {
      last.notes.push(continuation[1].trim());
      continue;
    }
    const comment = line.match(/^#\s?(.*)$/);
    if (comment) {
      if (comment[1].trim()) pending.push(comment[1].trim());
      last = null;
    } else if (!line.trim()) {
      last = null;
    }
  }
  return sections.filter((s) => s.vars.length);
}

const cell = (s) => s.replace(/\|/g, "\\|");
const code = (s) => `\`${s.replace(/`/g, "'")}\``;

function envTables(sections) {
  const out = [];
  for (const section of sections) {
    out.push(`### ${section.title}`, "", "| Variable | Default | What it does |", "|---|---|---|");
    for (const v of section.vars) {
      const def = v.active === null ? "*(not set)*" : v.active === "" ? "*(empty)*" : code(v.active);
      const examples = v.examples.length ? ` Examples: ${v.examples.map(code).join(", ")}.` : "";
      out.push(`| ${code(v.name)} | ${cell(def)} | ${cell(`${v.notes.join(" ")}${examples}`.trim())} |`);
    }
    out.push("");
  }
  return out;
}

function buildConfiguration() {
  const dashboard = existsSync(path.join(FRONTEND, ".env.local.example")) ? parseEnvTemplate("frontend/.env.local.example") : [];
  const lines = [
    "Every setting OpsPilot reads, generated from the configuration templates in the repository so it always matches the code.",
    "",
    "## Where settings live",
    "",
    "- **API and workers:** a `.env` file in the project root (a copy of `.env.example`). `start.cmd` creates one with fresh random secrets on first run. Real environment variables override the file.",
    "- **Dashboard:** `frontend/.env.local` (a copy of `frontend/.env.local.example`).",
    "- **Hosted deployments (Render, Vercel, Docker):** set the same names as environment variables in the platform's settings.",
    "- **Secrets:** API keys, database passwords, `SECRET_KEY` and `ENCRYPTION_KEY`. Never commit `.env` files or paste these into tickets or chat.",
    "",
    "## Minimum for production",
    "",
    "`/health/ready` reports what is missing. You need: `APP_ENV=production`, a PostgreSQL `DATABASE_URL`, a strong `SECRET_KEY`, an `ENCRYPTION_KEY`, an LLM provider with its API key, single sign-on (`OIDC_*`) with `ALLOW_PASSWORD_LOGIN=false`, `DEMO_PASSWORD` if the demo tenant is seeded, and your public host in `CORS_ORIGINS` and `MCP_ALLOWED_HOSTS`. See the [deployment guide](/help/deployment).",
    "",
    "## Common setups",
    "",
    "| Goal | Set |",
    "|---|---|",
    "| Neon (serverless PostgreSQL) | `DATABASE_URL` = the Neon connection string from the **direct** endpoint (host without `-pooler`), `ENABLE_PGVECTOR=true`, `DB_POOL_SIZE=5` |",
    "| Gemini | `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, Gemini model ids in `LLM_DEFAULT_MODEL` / `LLM_FAST_MODEL`, `LLM_MAX_OUTPUT_TOKENS=8192` |",
    "| Claude | `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, Claude model ids |",
    "| Fully offline | `LLM_PROVIDER=mock` and the SQLite `DATABASE_URL` (the defaults) |",
    "| More background workers | `WORKER_MODE=db`, then extra `python -m app.workers.runner` processes (or `start.cmd -Workers N`) |",
    "",
    "## API and workers (`.env`)",
    "",
    ...envTables(parseEnvTemplate(".env.example")),
    ...(dashboard.length ? ["## Dashboard (`frontend/.env.local`)", "", ...envTables(dashboard)] : []),
  ];
  addArticle({ slug: "configuration", title: "Configuration reference", group: "technical", source: ".env.example", docKey: ".env.example", rows: scan(lines.join("\n")) });
  linkMap.set(".env.example", "/help/configuration");
}

// --- link rewriting and output -------------------------------------------------------------------

function resolveLink(docKey, target) {
  if (/^(https?:|mailto:|\/help)/.test(target)) return target;
  const [file, hash] = target.split("#");
  const key = file ? path.posix.normalize(path.posix.join(path.posix.dirname(docKey), file)) : docKey;
  return (hash && linkMap.get(`${key}#${hash}`)) ?? linkMap.get(key) ?? null;
}

const SUMMARY_OVERRIDES = {
  glossary: "Plain-language definitions of the terms used across OpsPilot.",
};

function fallbackSummary(article, body) {
  if (SUMMARY_OVERRIDES[article.slug]) return SUMMARY_OVERRIDES[article.slug];
  const children = articles.filter((a) => a.parent === article.slug).map((a) => a.title);
  if (children.length) return `${children.join(" · ")}.`;
  const text = toPlainText(body);
  return text.length > 160 ? `${text.slice(0, 157).replace(/\s+\S*$/, "")}…` : text;
}

/** Every /help link must point at an existing article (and heading): a broken docs link fails the build. */
function brokenLinks(final) {
  const bySlug = new Map(final.map((a) => [a.slug, a]));
  const broken = [];
  for (const a of final) {
    for (const [, target] of a.body.matchAll(/\]\((\/help[^)\s]*)\)/g)) {
      const [slug, hash] = target.replace(/^\/help\/?/, "").split("#");
      const to = slug ? bySlug.get(slug) : null;
      if ((slug && !to) || (hash && to && !to.headings.some((h) => h.id === hash))) broken.push(`${a.slug} -> ${target}`);
    }
  }
  return broken;
}

function finalize(article) {
  const unresolved = [];
  let fence = false;
  const lines = article.rows.map((r) => {
    if (/^\s*(```|~~~)/.test(r.line)) fence = !fence;
    if (fence || r.level) return r.line;
    return r.line.replace(/(!?)\[([^\]]*)\]\(([^)\s]+)\)/g, (match, bang, text, target) => {
      if (bang) return match;
      const href = resolveLink(article.docKey, target);
      if (href !== null) return `[${text}](${href})`;
      unresolved.push(target);
      return text; // a source file outside the docs: keep the words, drop the link
    });
  });
  const body = lines.join("\n").trim();
  return {
    article: {
      slug: article.slug,
      title: article.title,
      group: article.group,
      source: article.source,
      ...(article.parent ? { parent: article.parent } : {}),
      summary: summaryOf(body) || fallbackSummary(article, body),
      headings: article.rows.filter((r) => r.level >= 2).map((r) => ({ id: r.anchor, text: plainInline(r.text), level: r.level })),
      body,
    },
    unresolved,
  };
}

if (!existsSync(path.join(ROOT, "docs", "USER_GUIDE.md"))) {
  console.log("[help] ../docs not found (build rooted at frontend/): keeping the committed lib/help/*.json");
  process.exit(0);
}

buildGuide("docs/USER_GUIDE.md");
for (const doc of WHOLE_DOCS) if (existsSync(path.join(ROOT, doc.file))) buildWholeDoc(doc);
buildConfiguration();

const built = articles.map(finalize);
const final = built.map((b) => b.article);
const slugs = new Set(final.map((a) => a.slug));
const tracks = JSON.parse(readFileSync(path.join(OUT_DIR, "tracks.json"), "utf8"));
const missing = tracks.flatMap((t) => {
  const listed = t.steps.flatMap((s) => s.articles);
  const dupes = listed.filter((slug, i) => listed.indexOf(slug) !== i).map((slug) => `${t.id}: ${slug} (listed twice)`);
  return [...listed.filter((slug) => !slugs.has(slug)).map((slug) => `${t.id}: ${slug}`), ...dupes];
});
if (missing.length) {
  console.error(`[help] tracks.json references unknown articles:\n  ${missing.join("\n  ")}\n[help] known: ${[...slugs].join(", ")}`);
  process.exit(1);
}
const broken = brokenLinks(final);
if (broken.length) {
  console.error(`[help] broken links:\n  ${broken.join("\n  ")}`);
  process.exit(1);
}

const files = [
  [path.join(OUT_DIR, "content.json"), `${JSON.stringify({ groups: GROUPS, articles: final })}\n`],
  [path.join(OUT_DIR, "index.json"), `${JSON.stringify(final.map((a) => ({ slug: a.slug, title: a.title, group: a.group })))}\n`],
];
if (CHECK) {
  const stale = files.filter(([file, data]) => !existsSync(file) || readFileSync(file, "utf8") !== data).map(([file]) => path.relative(FRONTEND, file));
  if (stale.length) {
    console.error(`[help] out of date: ${stale.join(", ")}. Run: npm run help:build`);
    process.exit(1);
  }
  console.log("[help] content is up to date");
} else {
  mkdirSync(OUT_DIR, { recursive: true });
  for (const [file, data] of files) writeFileSync(file, data);
  const unresolved = built.reduce((n, b) => n + b.unresolved.length, 0);
  console.log(`[help] ${final.length} articles${unresolved ? ` (${unresolved} links to non-doc files kept as plain text)` : ""}`);
}
