import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "BluBeauty", template: "%s · BluBeauty" },
  description: "Il gestionale per parrucchieri e centri estetici — by Blu Code Informatica",
  appleWebApp: { capable: true, title: "BluBeauty", statusBarStyle: "default" },
};

export const viewport: Viewport = { themeColor: "#1E5BD8" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="it" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
