"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { Clock } from "lucide-react";
import { useState, useEffect } from "react";
import { formatSingaporeClock } from "@/services/time";

const divisions = [
  {
    key: "overview",
    label: "Overview",
    href: "/",
    modules: [] as { key: string; label: string; href: string }[],
  },
  {
    key: "mobility",
    label: "Mobility",
    href: "/mobility/traffic",
    modules: [
      { key: "traffic", label: "Traffic", href: "/mobility/traffic" },
      { key: "transit", label: "Transit", href: "/mobility/transit" },
      { key: "roads", label: "Roads", href: "/mobility/roads" },
    ],
  },
  {
    key: "environment",
    label: "Environment",
    href: "/environment/pm25",
    modules: [
      { key: "pm25", label: "PM2.5", href: "/environment/pm25" },
      { key: "weather", label: "Weather", href: "/environment/weather" },
      { key: "flood", label: "Rain & Flood", href: "/environment/flood" },
    ],
  },
  {
    key: "safety",
    label: "Safety",
    href: "/safety/crime",
    modules: [
      { key: "crime", label: "Crime", href: "/safety/crime" },
      { key: "fire", label: "Fire", href: "/safety/fire" },
    ],
  },
  {
    key: "infrastructure",
    label: "Infrastructure",
    href: "/infrastructure/water",
    modules: [
      { key: "water", label: "Water", href: "/infrastructure/water" },
      { key: "waste", label: "Waste Management", href: "/infrastructure/waste" },
      { key: "energy", label: "Energy", href: "/infrastructure/energy" },
    ],
  },
  {
    key: "planning",
    label: "Planning",
    href: "/planning/housing",
    modules: [
      { key: "housing", label: "Housing", href: "/planning/housing" },
      { key: "land", label: "Land", href: "/planning/land" },
    ],
  },
];

export default function TopNav() {
  const pathname = usePathname();
  const [currentTime, setCurrentTime] = useState<string>("");

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(formatSingaporeClock(new Date()));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const activeDivision = divisions.find((d) => {
    if (d.key === "overview") return pathname === "/";
    return pathname.startsWith(`/${d.key}`);
  }) || divisions[0];

  const isActiveTop = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  return (
    <nav className="bg-white border-b border-slate-200 sticky top-0 z-50">
      {/* Primary top bar */}
      <div className="max-w-full mx-auto px-4 min-h-16 py-2 flex flex-wrap items-center justify-between gap-y-2">
        {/* Left brand */}
        <Link
          href="/"
          className="order-1 font-heading font-bold text-lg sm:text-xl text-[var(--color-primary)] tracking-wide flex items-center gap-2"
        >
          UrbanOS <span className="hidden sm:inline text-slate-500 font-normal">CITY INTELLIGENCE</span>
        </Link>

        {/* Center division tabs */}
        <nav aria-label="Divisions" className="order-3 flex w-full min-w-0 gap-5 overflow-x-auto whitespace-nowrap text-sm font-semibold tracking-wider lg:order-2 lg:ml-10 lg:mr-auto lg:w-auto lg:overflow-visible">
          {divisions.map((d) => (
            <Link
              key={d.key}
              href={d.href}
              className={`${isActiveTop(d.href)
                ? "text-indigo-600 border-b-2 border-[var(--color-primary)] pb-1"
                : "text-slate-500 hover:text-slate-900 transition-colors"}`}
            >
              {d.label}
            </Link>
          ))}
        </nav>

        {/* Right: LIVE indicator + clock */}
        <div className="order-2 ml-auto flex items-center space-x-3 sm:space-x-5 lg:order-3">
          <div className="flex items-center space-x-2 text-slate-500 text-sm font-mono">
            <Clock size={16} />
            <span>{currentTime}</span>
          </div>
        </div>
      </div>

      {/* Secondary module row */}
      {activeDivision.modules.length > 0 && (
        <div className="bg-slate-50 border-b border-slate-200">
          <div className="max-w-full mx-auto px-4">
            <div className="flex items-center h-10 gap-4 overflow-x-auto">
              {activeDivision.modules.map((m) => (
                <Link
                  key={m.key}
                  href={m.href}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors whitespace-nowrap ${
                    pathname === m.href
                      ? "text-white bg-indigo-600"
                      : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"
                  }`}
                >
                  {m.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </nav>
  );
}
