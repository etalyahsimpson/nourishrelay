import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/providers";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "NourishRelay — food recovery coordination demo",
  description:
    "Portfolio demonstration: move surplus food from offer to verified receipt without double booking. Synthetic data only.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
