"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { AlertTriangle, X } from "lucide-react";
import { forwardRef, useState, type ReactNode } from "react";

import { Button, type ButtonVariant } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export const DialogContent = forwardRef<React.ElementRef<typeof DialogPrimitive.Content>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { size?: "sm" | "md" | "lg" | "xl"; hideClose?: boolean }>(
  function DialogContent({ className, children, size = "md", hideClose, ...props }, ref) {
    const widths = { sm: "max-w-md", md: "max-w-lg", lg: "max-w-2xl", xl: "max-w-4xl" };
    return (
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm animate-fade-in" />
        <DialogPrimitive.Content
          ref={ref}
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-pop animate-zoom-in focus:outline-none",
            widths[size],
            className,
          )}
          {...props}
        >
          {children}
          {!hideClose ? (
            <DialogPrimitive.Close className="absolute right-3 top-3 rounded-md p-1.5 text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label="Close dialog">
              <X className="h-4 w-4" aria-hidden />
            </DialogPrimitive.Close>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    );
  },
);

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 border-b border-border px-5 py-4 pr-12", className)} {...props} />;
}

export const DialogTitle = forwardRef<React.ElementRef<typeof DialogPrimitive.Title>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>>(function DialogTitle({ className, ...props }, ref) {
  return <DialogPrimitive.Title ref={ref} className={cn("text-base font-semibold leading-tight text-fg", className)} {...props} />;
});

export const DialogDescription = forwardRef<React.ElementRef<typeof DialogPrimitive.Description>, React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>>(function DialogDescription({ className, ...props }, ref) {
  return <DialogPrimitive.Description ref={ref} className={cn("text-sm text-fg-muted", className)} {...props} />;
});

export function DialogBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("min-h-0 flex-1 overflow-y-auto px-5 py-4", className)} {...props} />;
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col-reverse gap-2 border-t border-border px-5 py-3 sm:flex-row sm:justify-end", className)} {...props} />;
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
  loading?: boolean;
  onConfirm: () => unknown;
  /** When set, the user must type this phrase to enable the confirm button. */
  requireText?: string;
  children?: ReactNode;
}

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Confirm", cancelLabel = "Cancel", tone = "primary", loading, onConfirm, requireText, children }: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const variant: ButtonVariant = tone === "danger" ? "danger" : "primary";
  const blocked = requireText ? typed.trim() !== requireText : false;
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setTyped("");
        onOpenChange(next);
      }}
    >
      <DialogContent size="sm">
        <DialogHeader>
          <div className="flex items-start gap-3">
            {tone === "danger" ? (
              <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-danger/15 text-danger">
                <AlertTriangle className="h-4 w-4" aria-hidden />
              </span>
            ) : null}
            <div className="min-w-0">
              <DialogTitle>{title}</DialogTitle>
              {description ? <DialogDescription className="mt-1">{description}</DialogDescription> : null}
            </div>
          </div>
        </DialogHeader>
        {children || requireText ? (
          <DialogBody className="space-y-3">
            {children}
            {requireText ? (
              <div className="space-y-1.5">
                <label htmlFor="confirm-text" className="text-xs text-fg-muted">
                  Type <span className="font-mono font-semibold text-fg">{requireText}</span> to confirm
                </label>
                <Input id="confirm-text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
              </div>
            ) : null}
          </DialogBody>
        ) : null}
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={loading}>
            {cancelLabel}
          </Button>
          <Button variant={variant} onClick={() => void onConfirm()} loading={loading} disabled={blocked}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
