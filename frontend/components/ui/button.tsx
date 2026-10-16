"use client";

import Link from "next/link";
import { Loader2 } from "lucide-react";
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "link";
export type ButtonSize = "xs" | "sm" | "md" | "lg" | "icon" | "icon-sm";

const base =
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-[background-color,border-color,color,box-shadow,transform] duration-150 select-none disabled:opacity-50 disabled:pointer-events-none active:translate-y-px";

const variants: Record<ButtonVariant, string> = {
  primary: "gradient-accent text-white shadow-soft hover:brightness-110 hover:shadow-glow border border-transparent",
  secondary: "bg-surface-2 text-fg border border-border hover:bg-surface-3 hover:border-border-strong",
  outline: "bg-transparent text-fg border border-border-strong hover:bg-surface-2",
  ghost: "bg-transparent text-fg-muted hover:text-fg hover:bg-surface-2 border border-transparent",
  danger: "bg-danger/15 text-danger border border-danger/40 hover:bg-danger/25",
  link: "bg-transparent text-accent underline-offset-4 hover:underline border border-transparent px-0 h-auto",
};

const sizes: Record<ButtonSize, string> = {
  xs: "h-7 px-2.5 text-xs",
  sm: "h-8 px-3 text-sm",
  md: "h-9 px-4 text-sm",
  lg: "h-11 px-5 text-base",
  icon: "h-9 w-9 p-0",
  "icon-sm": "h-8 w-8 p-0",
};

export function buttonVariants({ variant = "secondary", size = "md", className }: { variant?: ButtonVariant; size?: ButtonSize; className?: string }): string {
  return cn(base, variants[variant], sizes[size], className);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "secondary", size = "md", loading = false, leftIcon, rightIcon, children, disabled, type = "button", ...props },
  ref,
) {
  return (
    <button ref={ref} type={type} className={buttonVariants({ variant, size, className })} disabled={disabled || loading} aria-busy={loading || undefined} {...props}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : leftIcon}
      {children}
      {!loading && rightIcon}
    </button>
  );
});

export interface ButtonLinkProps {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
  children: ReactNode;
  leftIcon?: ReactNode;
  prefetch?: boolean;
  "aria-label"?: string;
}

export function ButtonLink({ href, variant = "secondary", size = "md", className, children, leftIcon, prefetch, ...rest }: ButtonLinkProps) {
  return (
    <Link href={href} prefetch={prefetch} className={buttonVariants({ variant, size, className })} {...rest}>
      {leftIcon}
      {children}
    </Link>
  );
}
