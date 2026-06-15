import type { Metadata } from "next";
import { IBM_Plex_Mono, Newsreader, Plus_Jakarta_Sans } from "next/font/google";
import { AppShell } from "@/components/app-shell";
import { Providers } from "./providers";
import "./globals.css";

const body = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-body" });
const display = Newsreader({ subsets: ["latin"], variable: "--font-display" });
const mono = IBM_Plex_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Arbiter | Prediction Market Trading",
  description: "Local control plane for multi-outcome prediction-market arbitrage.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${body.variable} ${display.variable} ${mono.variable}`}>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
