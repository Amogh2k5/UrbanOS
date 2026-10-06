"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { Activity, Clock } from "lucide-react";
import { format } from "date-fns";
import { useState, useEffect } from "react";

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
      { key: "energy", label: "Energy", href: "/infrastructure/energy" },
      { key: "utilities", label: "Utilities", href: "/infrastructure/utilities" },
    ],
  },
  {
    key: "planning",
    label: "Planning",
    href: "/planning/housing",
    modules: [
      { key: "housing", label: "Housing", href: "/planning/housing" },
      { key: "land", label: "Land", href: "/planning/land" },
      { key: "construction", label: "Construction", href: "/planning/construction" },
    ],
  },
];

export default function TopNav() {
  const pathname = usePathname();
  const [currentTime, setCurrentTime] = useState<string>("");

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrentTime(format(new Date(), "HH:mm:ss | dd MMM yyyy"));
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
    <nav className="bg-slate-950 border-b border-slate-800 sticky top-0 z-50">
      {/* Primary top bar */}
      <div className="max-w-full mx-auto px-4 h-16 flex items-center justify-between">
        {/* Left brand */}
        <Link
          href="/"
          className="font-heading font-bold text-xl text-[var(--color-primary)] tracking-wide flex items-center"
        >
          UrbanOS <span className="text-gray-400 font-normal">CITY INTELLIGENCE</span>
        </Link>

        {/* Center division tabs */}
        <nav className="flex space-x-6 text-sm font-semibold tracking-wider">
          {divisions.map((d) => (
            <Link
              key={d.key}
              href={d.href}
              className={`${isActiveTop(d.href)
                ? "text-white border-b-2 border-[var(--color-primary)] pb-1"
                : "text-gray-400 hover:text-white transition-colors"}`}
            >
              {d.label}
            </Link>
          ))}
        </nav>

        {/* Right: LIVE indicator + clock */}
        <div className="flex items-center space-x-6">
          <div className="flex items-center space-x-2 text-[var(--color-primary)] text-sm font-bold tracking-widest">
            <Activity size={16} className="animate-pulse" />
            <span>LIVE</span>
          </div>
          <div className="flex items-center space-x-2 text-gray-400 text-sm font-mono">
            <Clock size={16} />
            <span>{currentTime}</span>
          </div>
        </div>
      </div>

      {/* Secondary module row */}
      {activeDivision.modules.length > 0 && (
        <div className="bg-slate-900 border-b border-slate-800">
          <div className="max-w-full mx-auto px-4">
            <div className="flex items-center h-10 gap-4 overflow-x-auto">
              {activeDivision.modules.map((m) => (
                <Link
                  key={m.key}
                  href={m.href}
                  className={`px-3 py-1 text-xs font-medium rounded transition-colors whitespace-nowrap ${
                    pathname === m.href
                      ? "text-white bg-slate-700"
                      : "text-slate-400 hover:text-white hover:bg-slate-800"
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