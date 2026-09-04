import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";
import TopNav from "@/components/common/TopNav";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "UrbanOS City Intelligence",
  description: "Government Smart-City Command Center for Singapore",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} ${spaceGrotesk.variable} antialiased bg-black h-screen overflow-hidden text-slate-100 flex flex-col`}
      >
        <TopNav />
        <main className="flex-1 overflow-auto pt-16">{children}</main>
      </body>
    </html>
  );
}
