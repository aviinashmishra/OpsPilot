"use client";

import { Search, Wrench } from "lucide-react";
import { useMemo, useState } from "react";

import { MethodTag } from "@/components/integrations/custom-tools-tab";
import { Badge, RiskBadge } from "@/components/ui/badge";
import { Input, NativeSelect } from "@/components/ui/input";
import { Segmented } from "@/components/ui/misc";
import { Pagination } from "@/components/ui/pagination";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { useDebounced } from "@/lib/hooks";
import { useToolCatalog } from "@/lib/queries";
import { fmtInt, titleCase } from "@/lib/utils";

const PAGE = 25;

type Source = "all" | "builtin" | "custom";
type Effect = "all" | "read" | "write";

interface CatalogRow {
  key: string;
  name: string;
  description: string;
  provider: string;
  side_effect: boolean;
  risk_level: string;
  required_permission: string;
  used_by: string[];
  calls_30d: number;
  source: "builtin" | "custom";
  method?: string;
  enabled?: boolean;
}

export function ToolCatalogTab() {
  const catalog = useToolCatalog();
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, 150);
  const [source, setSource] = useState<Source>("all");
  const [provider, setProvider] = useState("");
  const [effect, setEffect] = useState<Effect>("all");
  const [risk, setRisk] = useState("");
  const [offset, setOffset] = useState(0);

  const rows: CatalogRow[] = useMemo(() => {
    if (!catalog.data) return [];
    const builtin: CatalogRow[] = catalog.data.builtin.map((t) => ({ ...t, source: "builtin" as const }));
    const custom: CatalogRow[] = catalog.data.custom.map((t) => ({
      key: t.key,
      name: t.name,
      description: t.description,
      provider: "custom",
      side_effect: t.side_effect,
      risk_level: t.risk_level,
      required_permission: "tools:custom",
      used_by: [],
      calls_30d: t.calls_30d,
      source: "custom" as const,
      method: t.method,
      enabled: t.enabled,
    }));
    return [...custom, ...builtin];
  }, [catalog.data]);

  const providers = useMemo(() => Array.from(new Set(rows.map((r) => r.provider))).sort(), [rows]);

  const filtered = useMemo(() => {
    const q = debounced.trim().toLowerCase();
    return rows.filter(
      (r) =>
        (source === "all" || r.source === source) &&
        (!provider || r.provider === provider) &&
        (effect === "all" || (effect === "write" ? r.side_effect : !r.side_effect)) &&
        (!risk || r.risk_level === risk) &&
        (!q || r.key.toLowerCase().includes(q) || r.name.toLowerCase().includes(q) || r.description.toLowerCase().includes(q) || r.used_by.some((a) => a.includes(q))),
    );
  }, [rows, debounced, source, provider, effect, risk]);

  const page = filtered.slice(offset, offset + PAGE);
  const resetPage = () => setOffset(0);

  if (catalog.isError) return <ErrorState error={catalog.error} onRetry={() => catalog.refetch()} />;
  if (catalog.isLoading) return <SkeletonRows rows={8} />;

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 lg:flex-row lg:flex-wrap lg:items-center">
        <div className="relative lg:w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
          <Input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              resetPage();
            }}
            placeholder="Search tools, descriptions, agents…"
            className="pl-8"
            aria-label="Search tools"
          />
        </div>
        <Segmented<Source>
          aria-label="Source"
          value={source}
          onChange={(v) => {
            setSource(v);
            resetPage();
          }}
          options={[
            { value: "all", label: `All · ${rows.length}` },
            { value: "builtin", label: `Built-in · ${catalog.data?.builtin.length ?? 0}` },
            { value: "custom", label: `Custom · ${catalog.data?.custom.length ?? 0}` },
          ]}
        />
        <div className="grid grid-cols-3 gap-2 lg:flex">
          <NativeSelect
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              resetPage();
            }}
            className="h-8 text-xs lg:w-40"
            aria-label="Provider"
          >
            <option value="">All providers</option>
            {providers.map((p) => (
              <option key={p} value={p}>
                {titleCase(p)}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            value={effect}
            onChange={(e) => {
              setEffect(e.target.value as Effect);
              resetPage();
            }}
            className="h-8 text-xs lg:w-36"
            aria-label="Side effect"
          >
            <option value="all">Any effect</option>
            <option value="read">Read-only</option>
            <option value="write">Side effect</option>
          </NativeSelect>
          <NativeSelect
            value={risk}
            onChange={(e) => {
              setRisk(e.target.value);
              resetPage();
            }}
            className="h-8 text-xs lg:w-32"
            aria-label="Risk"
          >
            <option value="">Any risk</option>
            {["low", "medium", "high", "critical"].map((r) => (
              <option key={r} value={r}>
                {titleCase(r)}
              </option>
            ))}
          </NativeSelect>
        </div>
        <p className="text-xs text-fg-subtle tabular lg:ml-auto">{fmtInt(filtered.length)} tools</p>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon={Wrench} title="No tools match" description="Try a different search or clear the filters." />
      ) : (
        <TableWrap>
          <Table className="min-w-[980px]">
            <THead>
              <TR>
                <TH>Tool</TH>
                <TH>Provider</TH>
                <TH>Side effect</TH>
                <TH>Risk</TH>
                <TH>Permission</TH>
                <TH>Used by</TH>
                <TH align="right">Calls · 30 d</TH>
              </TR>
            </THead>
            <TBody>
              {page.map((tool) => (
                <TR key={tool.key}>
                  <TD className="max-w-[340px]">
                    <span className="flex items-center gap-1.5">
                      {tool.method ? <MethodTag method={tool.method} /> : null}
                      <code className="font-mono text-xs font-medium text-fg">{tool.key}</code>
                      {tool.source === "custom" ? (
                        <Badge size="sm" tone="accent">
                          custom
                        </Badge>
                      ) : null}
                      {tool.enabled === false ? <Badge size="sm">disabled</Badge> : null}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-fg-muted" title={tool.description}>
                      {tool.description}
                    </span>
                  </TD>
                  <TD className="text-xs text-fg-muted">{titleCase(tool.provider)}</TD>
                  <TD>
                    {tool.side_effect ? (
                      <Badge size="sm" tone="warning">
                        side effect
                      </Badge>
                    ) : (
                      <Badge size="sm">read-only</Badge>
                    )}
                  </TD>
                  <TD>
                    <RiskBadge level={tool.risk_level} size="sm" />
                  </TD>
                  <TD>
                    <code className="font-mono text-[11px] text-fg-muted">{tool.required_permission}</code>
                  </TD>
                  <TD className="text-xs">
                    {tool.source === "custom" ? (
                      <span className="text-fg-muted">Copilot</span>
                    ) : tool.used_by.length === 0 ? (
                      <span className="text-fg-subtle">no agents</span>
                    ) : (
                      <Tip
                        content={
                          <ul className="space-y-0.5 font-mono text-[11px]">
                            {tool.used_by.map((a) => (
                              <li key={a}>{a}</li>
                            ))}
                          </ul>
                        }
                      >
                        <button type="button" className="cursor-help rounded text-fg underline decoration-dotted underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
                          {tool.used_by.length} agent{tool.used_by.length === 1 ? "" : "s"}
                        </button>
                      </Tip>
                    )}
                  </TD>
                  <TD align="right" className={tool.calls_30d === 0 ? "text-fg-subtle" : undefined}>
                    {fmtInt(tool.calls_30d)}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </TableWrap>
      )}
      <Pagination total={filtered.length} limit={PAGE} offset={offset} onChange={setOffset} label="tools" />
    </div>
  );
}
