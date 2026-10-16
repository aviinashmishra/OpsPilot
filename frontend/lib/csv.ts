/** Minimal RFC 4180-style CSV parser (quoted fields, escaped quotes, CRLF, embedded newlines). */
export function parseCsv(text: string, delimiter = ","): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  const src = text.replace(/^﻿/, "");
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"' && field === "") {
      quoted = true;
    } else if (ch === delimiter) {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += ch;
    }
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => r.some((cell) => cell.trim() !== ""));
}

/** Guess the delimiter from the header line (comma, semicolon or tab). */
export function sniffDelimiter(text: string): string {
  const header = text.split(/\r?\n/, 1)[0] ?? "";
  const counts: Array<[string, number]> = [",", ";", "\t"].map((d) => [d, header.split(d).length - 1]);
  counts.sort((a, b) => b[1] - a[1]);
  return counts[0][1] > 0 ? counts[0][0] : ",";
}

function coerce(value: string): unknown {
  const v = value.trim();
  if (v === "") return undefined;
  if (v === "true") return true;
  if (v === "false") return false;
  if (v === "null") return null;
  if (/^-?(0|[1-9]\d{0,14})(\.\d+)?$/.test(v)) return Number(v);
  if ((v.startsWith("{") && v.endsWith("}")) || (v.startsWith("[") && v.endsWith("]"))) {
    try {
      return JSON.parse(v) as unknown;
    } catch {
      return v;
    }
  }
  return v;
}

function setPath(target: Record<string, unknown>, path: string, value: unknown): void {
  const parts = path.split(".").map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return;
  let node = target;
  for (const part of parts.slice(0, -1)) {
    const next = node[part];
    if (typeof next !== "object" || next === null || Array.isArray(next)) node[part] = {};
    node = node[part] as Record<string, unknown>;
  }
  node[parts[parts.length - 1]] = value;
}

export interface CsvToObjectsResult {
  items: Record<string, unknown>[];
  columns: string[];
  error: string | null;
}

/**
 * Converts CSV text with a header row into objects. Numbers / booleans / JSON cells are
 * coerced, empty cells are omitted, dotted headers ("lead.email") build nested objects, and
 * `wrapKey` (e.g. "lead") wraps each row as `{ [wrapKey]: row }`.
 */
export function csvToObjects(text: string, wrapKey?: string): CsvToObjectsResult {
  if (!text.trim()) return { items: [], columns: [], error: null };
  const rows = parseCsv(text, sniffDelimiter(text));
  if (rows.length < 2) return { items: [], columns: rows[0] ?? [], error: "Add a header row and at least one data row." };
  const columns = rows[0].map((c) => c.trim());
  if (columns.some((c) => !c)) return { items: [], columns, error: "Every header cell needs a name." };
  const items = rows.slice(1).map((cells) => {
    const obj: Record<string, unknown> = {};
    columns.forEach((col, i) => {
      const value = coerce(cells[i] ?? "");
      if (value !== undefined) setPath(obj, col, value);
    });
    const key = wrapKey?.trim();
    return key ? { [key]: obj } : obj;
  });
  return { items, columns, error: null };
}
