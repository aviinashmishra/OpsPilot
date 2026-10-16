import { Fragment, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Tiny, safe markdown renderer for assistant text. It understands paragraphs,
 * line breaks, headings, bullet / numbered lists (with indented continuation
 * lines), fenced code, `inline code`, **bold**, *italic* and [links](https://…).
 * Everything is rendered as React text nodes: model output never reaches
 * dangerouslySetInnerHTML, and only http(s) links are turned into anchors.
 */

interface ListItem {
  text: string;
  sub: string[];
}

type Block =
  | { type: "p"; lines: string[] }
  | { type: "h"; level: number; text: string }
  | { type: "ul"; items: ListItem[] }
  | { type: "ol"; items: ListItem[]; start: number }
  | { type: "code"; text: string }
  | { type: "hr" };

const BULLET = /^(\s*)[-*•+]\s+(.*)$/;
const ORDERED = /^(\s*)(\d{1,3})[.)]\s+(.*)$/;
const HEADING = /^(#{1,4})\s+(.*)$/;
const FENCE = /^\s*```/;
const HR = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/;

export function parseMarkdown(source: string): Block[] {
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let current: Block | null = null;

  const flush = () => {
    if (current) blocks.push(current);
    current = null;
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];

    if (FENCE.test(line)) {
      flush();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !FENCE.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      blocks.push({ type: "code", text: body.join("\n") });
      continue;
    }

    if (!line.trim()) {
      flush();
      continue;
    }

    if (HR.test(line)) {
      flush();
      blocks.push({ type: "hr" });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      flush();
      blocks.push({ type: "h", level: heading[1].length, text: heading[2].trim() });
      continue;
    }

    const bullet = BULLET.exec(line);
    const ordered = bullet ? null : ORDERED.exec(line);
    const indent = (bullet?.[1] ?? ordered?.[1] ?? "").length;
    const open = current as Block | null;

    if ((bullet || ordered) && open && (open.type === "ul" || open.type === "ol") && indent >= 2 && open.items.length > 0) {
      // Nested list item: keep it under the previous item.
      open.items[open.items.length - 1].sub.push((bullet ? bullet[2] : ordered?.[3]) ?? "");
      continue;
    }

    if (bullet) {
      if (!open || open.type !== "ul") {
        flush();
        current = { type: "ul", items: [] };
      }
      (current as Extract<Block, { type: "ul" }>).items.push({ text: bullet[2], sub: [] });
      continue;
    }

    if (ordered) {
      if (!open || open.type !== "ol") {
        flush();
        current = { type: "ol", items: [], start: Number(ordered[2]) || 1 };
      }
      (current as Extract<Block, { type: "ol" }>).items.push({ text: ordered[3], sub: [] });
      continue;
    }

    if (open && (open.type === "ul" || open.type === "ol") && /^\s{2,}\S/.test(line) && open.items.length > 0) {
      // Indented continuation line of the previous list item.
      open.items[open.items.length - 1].sub.push(line.trim());
      continue;
    }

    if (!open || open.type !== "p") {
      flush();
      current = { type: "p", lines: [] };
    }
    (current as Extract<Block, { type: "p" }>).lines.push(line.trim());
  }
  flush();
  return blocks;
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*|__[^_\n]+?__)|(\[[^\]\n]+\]\((https?:\/\/[^\s)]+)\))|(\*[^*\s\n][^*\n]*?\*|_[^_\s\n][^_\n]*?_(?=\W|$))/g;

export function renderInline(text: string, keyPrefix = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of Array.from(text.matchAll(INLINE))) {
    const start = match.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    const key = `${keyPrefix}-${index++}`;
    const [token, code, bold, link, href, italic] = match;
    if (code) {
      out.push(
        <code key={key} className="rounded bg-surface-3/80 px-1 py-px font-mono text-[0.85em] text-fg">
          {code.slice(1, -1)}
        </code>,
      );
    } else if (bold) {
      out.push(
        <strong key={key} className="font-semibold text-fg">
          {renderInline(bold.slice(2, -2), key)}
        </strong>,
      );
    } else if (link && href) {
      const label = link.slice(1, link.indexOf("]("));
      out.push(
        <a key={key} href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline-offset-2 hover:underline">
          {label}
        </a>,
      );
    } else if (italic) {
      out.push(
        <em key={key} className="italic">
          {italic.slice(1, -1)}
        </em>,
      );
    } else {
      out.push(token);
    }
    last = start + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Lines({ lines, prefix }: { lines: string[]; prefix: string }) {
  return (
    <>
      {lines.map((line, i) => (
        <Fragment key={`${prefix}-${i}`}>
          {i > 0 ? <br /> : null}
          {renderInline(line, `${prefix}-${i}`)}
        </Fragment>
      ))}
    </>
  );
}

function Items({ items, prefix }: { items: ListItem[]; prefix: string }) {
  return (
    <>
      {items.map((item, i) => (
        <li key={`${prefix}-${i}`} className="pl-1 marker:text-fg-subtle">
          {renderInline(item.text, `${prefix}-${i}`)}
          {item.sub.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-[0.95em] text-fg-muted">
              {item.sub.map((s, j) => (
                <li key={j} className="break-words">
                  {renderInline(s, `${prefix}-${i}-${j}`)}
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </>
  );
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks = parseMarkdown(text);
  return (
    <div className={cn("space-y-2.5 break-words text-sm leading-relaxed text-fg", className)}>
      {blocks.map((block, i) => {
        const key = `b${i}`;
        switch (block.type) {
          case "h":
            return (
              <p key={key} className={cn("font-semibold text-fg", block.level <= 2 ? "text-[15px]" : "text-sm")}>
                {renderInline(block.text, key)}
              </p>
            );
          case "ul":
            return (
              <ul key={key} className="list-disc space-y-1.5 pl-5">
                <Items items={block.items} prefix={key} />
              </ul>
            );
          case "ol":
            return (
              <ol key={key} start={block.start} className="list-decimal space-y-1.5 pl-5">
                <Items items={block.items} prefix={key} />
              </ol>
            );
          case "code":
            return (
              <pre key={key} className="overflow-x-auto rounded-md border border-border bg-bg/60 p-3 font-mono text-[12px] leading-relaxed text-fg">
                <code>{block.text}</code>
              </pre>
            );
          case "hr":
            return <hr key={key} className="border-border" />;
          default:
            return (
              <p key={key}>
                <Lines lines={block.lines} prefix={key} />
              </p>
            );
        }
      })}
    </div>
  );
}
