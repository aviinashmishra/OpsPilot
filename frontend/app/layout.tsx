import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import type { ReactNode } from "react";

import { AppProviders } from "@/components/providers/app-providers";
import { themeInitScript } from "@/components/providers/theme-provider";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], display: "swap", variable: "--font-inter", fallback: ["system-ui", "Segoe UI", "Roboto", "sans-serif"] });

export const metadata: Metadata = {
  title: { default: "OpsPilot AI", template: "%s · OpsPilot AI" },
  description: "Administrative dashboard for the OpsPilot AI workforce platform.",
  applicationName: "OpsPilot AI",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0b1020" },
    { media: "(prefers-color-scheme: light)", color: "#f5f6fa" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={inter.variable}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="font-sans">
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:text-sm focus:shadow-pop">
          Skip to content
        </a>
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
