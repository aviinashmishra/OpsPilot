"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FilePlus2, FileText, Search, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Badge, StatusPill } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardToolbar } from "@/components/ui/card";
import { ConfirmDialog, Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, Input, NativeSelect, Textarea } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { SkeletonRows } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { TBody, TD, TH, THead, TR, Table, TableWrap } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { api, errorMessage } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import { usePermission } from "@/lib/permissions";
import { useDocumentSearch, useDocuments } from "@/lib/queries";
import type { DocumentOut, DocumentTextIn } from "@/lib/types";
import { fmtBytes, fmtDateTime, fmtRelative, titleCase } from "@/lib/utils";

const CLASSIFICATION_TONE: Record<string, "neutral" | "info" | "warning" | "danger"> = { public: "neutral", internal: "info", confidential: "warning", restricted: "danger" };

export default function DocumentsPage() {
  const [collection, setCollection] = useState("");
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [deleting, setDeleting] = useState<DocumentOut | null>(null);
  const q = useDebounced(query.trim(), 400);
  const canWrite = usePermission("documents:write");
  const queryClient = useQueryClient();
  const documents = useDocuments(collection || undefined);
  const allDocuments = useDocuments(undefined, { enabled: Boolean(collection) });
  const search = useDocumentSearch(q);

  const collections = useMemo(() => Array.from(new Set((allDocuments.data ?? documents.data ?? []).map((d) => d.collection))).sort(), [allDocuments.data, documents.data]);

  const remove = useMutation({
    mutationFn: (doc: DocumentOut) => api<void>(`/documents/${doc.id}`, { method: "DELETE" }),
    onSuccess: (_, doc) => {
      toast.success("Document deleted", { description: doc.name });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["document-search"] });
      setDeleting(null);
    },
    onError: (error) => toast.error("Could not delete document", { description: errorMessage(error) }),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Documents"
        actions={
          <Button variant="primary" onClick={() => setAddOpen(true)} disabled={!canWrite} leftIcon={<FilePlus2 className="h-4 w-4" aria-hidden />}>
            Add text document
          </Button>
        }
      />

      <Card>
        <CardToolbar title="Search the knowledge base" description="Shows exactly what agents will find." />
        <CardContent className="space-y-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-subtle" aria-hidden />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search for a policy, case study, FAQ… (min 2 characters)" className="pl-8" aria-label="Search documents" />
          </div>
          {search.isError ? <ErrorState error={search.error} onRetry={() => search.refetch()} compact /> : null}
          {q.length >= 2 && search.isLoading ? <SkeletonRows rows={3} /> : null}
          {search.data && q.length >= 2 ? (
            search.data.items.length === 0 ? (
              <p className="text-sm text-fg-subtle">No matching chunks.</p>
            ) : (
              <ul className="space-y-2">
                {search.data.items.map((hit) => (
                  <li key={hit.ref} className="rounded-md border border-border bg-surface-2/50 p-3">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-medium text-fg">{hit.document_name}</span>
                      <Badge size="sm">{hit.collection}</Badge>
                      {hit.section ? <span className="text-fg-muted">§ {hit.section}</span> : null}
                      <span className="ml-auto text-fg-subtle tabular">score {hit.score.toFixed(3)}</span>
                    </div>
                    <p className="mt-1 line-clamp-3 whitespace-pre-line text-sm text-fg-muted">{hit.text}</p>
                    <code className="mt-1 block font-mono text-[11px] text-fg-subtle">{hit.ref}</code>
                  </li>
                ))}
              </ul>
            )
          ) : null}
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <NativeSelect value={collection} onChange={(e) => setCollection(e.target.value)} aria-label="Collection" className="w-full sm:w-56">
          <option value="">All collections</option>
          {collections.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </NativeSelect>
        {documents.data ? <span className="text-xs text-fg-muted">{documents.data.length} documents</span> : null}
      </div>

      {documents.isError ? <ErrorState error={documents.error} onRetry={() => documents.refetch()} /> : null}
      {documents.isLoading ? (
        <SkeletonRows rows={6} />
      ) : documents.data && documents.data.length === 0 ? (
        <EmptyState icon={FileText} title="No documents" description="Add a text document to make it available to agents." />
      ) : documents.data ? (
        <TableWrap>
          <Table className="min-w-[860px]">
            <THead>
              <TR>
                <TH>Document</TH>
                <TH>Collection</TH>
                <TH>Classification</TH>
                <TH>Scan</TH>
                <TH align="right">Chunks</TH>
                <TH align="right">Size</TH>
                <TH>Added</TH>
                <TH align="right">
                  <span className="sr-only">Actions</span>
                </TH>
              </TR>
            </THead>
            <TBody>
              {documents.data.map((doc) => (
                <TR key={doc.id}>
                  <TD>
                    <span className="font-medium text-fg">{doc.name}</span>
                    <span className="block font-mono text-[11px] text-fg-subtle">
                      {doc.content_type}
                      {doc.sha256 ? ` · ${doc.sha256.slice(0, 12)}…` : ""}
                    </span>
                  </TD>
                  <TD>
                    <Badge size="sm">{doc.collection}</Badge>
                  </TD>
                  <TD>
                    <Badge size="sm" tone={CLASSIFICATION_TONE[doc.classification] ?? "neutral"}>
                      {titleCase(doc.classification)}
                    </Badge>
                  </TD>
                  <TD>
                    <span className="inline-flex items-center gap-1">
                      <StatusPill status={doc.scan_status} size="sm" />
                      {doc.scan_findings.length > 0 ? <span className="text-xs text-fg-muted">{doc.scan_findings.length} finding{doc.scan_findings.length > 1 ? "s" : ""}</span> : null}
                    </span>
                  </TD>
                  <TD align="right">{doc.chunk_count}</TD>
                  <TD align="right">{fmtBytes(doc.size_bytes)}</TD>
                  <TD>
                    <Tip content={fmtDateTime(doc.created_at)}>
                      <time dateTime={doc.created_at} className="text-fg-muted">
                        {fmtRelative(doc.created_at)}
                      </time>
                    </Tip>
                  </TD>
                  <TD align="right">
                    <Button size="icon-sm" variant="ghost" aria-label={`Delete ${doc.name}`} disabled={!canWrite} onClick={() => setDeleting(doc)}>
                      <Trash2 className="h-4 w-4 text-danger" aria-hidden />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </TableWrap>
      ) : null}

      <AddDocumentDialog open={addOpen} onOpenChange={setAddOpen} collections={collections} />
      <ConfirmDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)} title="Delete this document?" description={deleting ? `${deleting.name} and its ${deleting.chunk_count} indexed chunk(s) will be removed. Agents can no longer cite it.` : undefined} confirmLabel="Delete" tone="danger" loading={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} />
    </div>
  );
}

function AddDocumentDialog({ open, onOpenChange, collections }: { open: boolean; onOpenChange: (open: boolean) => void; collections: string[] }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [collection, setCollection] = useState("kb");
  const [classification, setClassification] = useState<DocumentTextIn["classification"]>("internal");
  const [text, setText] = useState("");

  const create = useMutation({
    mutationFn: () => {
      const body: DocumentTextIn = { name: name.trim(), collection: collection.trim() || "kb", classification, text, meta: { source: "dashboard" } };
      return api<DocumentOut>("/documents/text", { method: "POST", body });
    },
    onSuccess: (doc) => {
      toast[doc.scan_status === "flagged" ? "warning" : "success"](doc.scan_status === "flagged" ? "Document added but flagged by the scanner" : "Document added", { description: `${doc.name} · ${doc.chunk_count} chunk(s)` });
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      onOpenChange(false);
      setName("");
      setText("");
    },
    onError: (error) => toast.error("Could not add document", { description: errorMessage(error) }),
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate();
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <form onSubmit={submit} className="flex min-h-0 flex-col">
          <DialogHeader>
            <DialogTitle>Add a text document</DialogTitle>
            <DialogDescription>The text is scanned for secrets and prompt-injection patterns, then chunked and indexed.</DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <Field label="Name" htmlFor="doc-name" required>
              <Input id="doc-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={300} required />
            </Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Collection" htmlFor="doc-collection" hint={collections.length ? `Existing: ${collections.join(", ")}` : undefined}>
                <Input id="doc-collection" value={collection} onChange={(e) => setCollection(e.target.value)} maxLength={64} list="doc-collections" />
                <datalist id="doc-collections">
                  {collections.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </Field>
              <Field label="Classification" htmlFor="doc-class">
                <NativeSelect id="doc-class" value={classification} onChange={(e) => setClassification(e.target.value as DocumentTextIn["classification"])}>
                  {["public", "internal", "confidential", "restricted"].map((c) => (
                    <option key={c} value={c}>
                      {titleCase(c)}
                    </option>
                  ))}
                </NativeSelect>
              </Field>
            </div>
            <Field label="Text" htmlFor="doc-text" required>
              <Textarea id="doc-text" value={text} onChange={(e) => setText(e.target.value)} rows={10} required placeholder="# Refund policy&#10;Customers may request a refund within 30 days…" />
            </Field>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" type="button" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" loading={create.isPending} disabled={!name.trim() || !text.trim()}>
              Add document
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
