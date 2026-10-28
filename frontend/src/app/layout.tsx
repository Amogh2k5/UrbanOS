import type { Metadata } from "next";
import "./globals.css";
import TopNav from "@/components/common/TopNav";

export const metadata: Metadata = {
  title: "UrbanOS City Intelligence",
  description: "Government Smart-City Command Center for Singapore",
};

export const dynamic = 'force-dynamic';

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased bg-background min-h-screen text-foreground flex flex-col">
        <TopNav />
        <main className="flex-1 overflow-visible">{children}</main>
      </body>
    </html>
  );
}
