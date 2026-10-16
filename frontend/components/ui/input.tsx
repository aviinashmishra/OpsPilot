import { forwardRef, type InputHTMLAttributes, type LabelHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export const inputClasses =
  "flex h-9 w-full rounded-md border border-border bg-surface px-3 text-sm text-fg shadow-none transition-colors placeholder:text-fg-subtle hover:border-border-strong focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-60 disabled:cursor-not-allowed aria-[invalid=true]:border-danger";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(inputClasses, className)} {...props} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn(inputClasses, "h-auto min-h-[88px] py-2 leading-relaxed", className)} {...props} />;
});

export function Label({ className, ...props }: LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-xs font-medium text-fg-muted", className)} {...props} />;
}

export function Field({ label, htmlFor, hint, error, required, children, className }: { label: ReactNode; htmlFor?: string; hint?: ReactNode; error?: ReactNode; required?: boolean; children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={htmlFor}>
        {label}
        {required ? (
          <span className="ml-0.5 text-danger" aria-hidden>
            *
          </span>
        ) : null}
      </Label>
      {children}
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-fg-subtle">{hint}</p>
      ) : null}
    </div>
  );
}

/** Native select used for compact filters (keyboard accessible, no portal). */
export const NativeSelect = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function NativeSelect({ className, children, ...props }, ref) {
  return (
    <select ref={ref} className={cn(inputClasses, "appearance-none bg-[length:16px_16px] bg-[right_8px_center] bg-no-repeat pr-8", className)} style={{ backgroundImage: "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%238a93a6' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><polyline points='6 9 12 15 18 9'/></svg>\")" }} {...props}>
      {children}
    </select>
  );
});
