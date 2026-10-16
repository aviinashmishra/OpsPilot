"use client";

import Link from "next/link";
import type { ComponentPropsWithoutRef, ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { HelpHeading } from "@/lib/help/content";
import { cn } from "@/lib/utils";

const HEADING_CLASSES: Record<number, string> = {
  2: "mt-10 border-b border-border pb-2 text-lg font-semibold tracking-tight",
  3: "mt-8 text-base font-semibold",
  4: "mt-6 text-sm font-semibold",
  5: "mt-5 text-sm font-semibold text-fg-muted",
  6: "mt-5 text-xs font-semibold uppercase tracking-wide text-fg-muted",
};

function HelpLink({ href = "", children, ...rest }: ComponentPropsWithoutRef<"a">) {
  const className = "font-medium text-accent underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 rounded-sm";
  if (href.startsWith("/") || href.startsWith("#")) {
    return (
      <Link href={href} className={className}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className} {...rest}>
      {children}
    </a>
  );
}

interface HastNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

/**
 * Rehype plugin: stamps the generator's heading ids (the source document's GitHub anchors) onto
 * the headings in document order, so links like /help/admin#api-keys land on the right section.
 */
function headingIds(headings: HelpHeading[]) {
  return () => (tree: HastNode) => {
    let i = 0;
    const walk = (node: HastNode) => {
      if (node.type === "element" && /^h[1-6]$/.test(node.tagName ?? "")) {
        const id = headings[i++]?.id;
        if (id) node.properties = { ...node.properties, id };
      }
      node.children?.forEach(walk);
    };
    walk(tree);
  };
}

const heading = (level: number) =>
  function Heading({ id, children }: { id?: string; children?: ReactNode }) {
    const Tag = `h${level}` as "h2";
      return (
        <Tag id={id} className={cn("group scroll-mt-20 text-fg", HEADING_CLASSES[level])}>
          {children}
          {id ? (
            <a href={`#${id}`} className="ml-2 text-fg-subtle opacity-0 transition-opacity hover:text-accent group-hover:opacity-100 focus-visible:opacity-100" aria-label="Link to this section">
              #
            </a>
          ) : null}
      </Tag>
    );
  };

const COMPONENTS: Components = {
  h1: heading(2),
  h2: heading(2),
  h3: heading(3),
  h4: heading(4),
  h5: heading(5),
  h6: heading(6),
  p: ({ children }) => <p className="mt-3 leading-7 text-fg/90">{children}</p>,
  a: ({ node: _node, ...props }) => <HelpLink {...props} />,
  ul: ({ children }) => <ul className="mt-3 list-disc space-y-1.5 pl-6 leading-7 text-fg/90 marker:text-fg-subtle">{children}</ul>,
  ol: ({ children }) => <ol className="mt-3 list-decimal space-y-1.5 pl-6 leading-7 text-fg/90 marker:text-fg-subtle">{children}</ol>,
  li: ({ children }) => <li className="pl-1 [&>p]:mt-1 [&>ul]:mt-1.5 [&>ol]:mt-1.5">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-fg">{children}</strong>,
  blockquote: ({ children }) => <blockquote className="mt-4 rounded-r-md border-l-2 border-accent/60 bg-accent/5 px-4 py-1 text-fg-muted">{children}</blockquote>,
  hr: () => <hr className="my-8 border-border" />,
  table: ({ children }) => (
    <div className="mt-4 overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-left text-[13px] leading-6">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-2 text-xs font-semibold text-fg-muted">{children}</thead>,
  th: ({ children }) => <th className="whitespace-nowrap border-b border-border px-3 py-2 align-bottom">{children}</th>,
  td: ({ children }) => <td className="border-b border-border/70 px-3 py-2 align-top text-fg/90 [tr:last-child_&]:border-b-0">{children}</td>,
  pre: ({ children }) => <pre className="mt-4 overflow-x-auto rounded-lg border border-border bg-surface-2 p-4 font-mono text-[12.5px] leading-6 text-fg [&>code]:bg-transparent [&>code]:p-0">{children}</pre>,
  code: ({ children, className }) => <code className={cn("rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[0.85em] text-fg", className)}>{children}</code>,
};

/** Renders a help article's markdown with the dashboard's typography. */
export function HelpMarkdown({ body, headings }: { body: string; headings: HelpHeading[] }) {
  return (
    <div className="min-w-0 text-sm" data-testid="help-article-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[headingIds(headings)]} components={COMPONENTS}>
        {body}
      </ReactMarkdown>
    </div>
  );
}
