"use client";

import { Clock } from 'lucide-react';
import { useState, useEffect } from 'react';
import { formatSingaporeClock } from '@/services/time';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

export default function TopBar() {
  const [currentTime, setCurrentTime] = useState<string>('');
  const pathname = usePathname();

  useEffect(() => {
    // Use a small initial delay if we don't want a flash, but setting state directly in effect is frowned upon.
    // Instead we can just let the interval run.
    const interval = setInterval(() => {
      setCurrentTime(formatSingaporeClock(new Date()));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const navItems = [
    { name: 'OVERVIEW', path: '/' },
    { name: 'WEATHER', path: '/environment/weather' },
    { name: 'POLLUTION', path: '/environment/pm25' },
    { name: 'FLOOD', path: '/environment/flood' },
    { name: 'TRAFFIC', path: '/mobility/traffic' },
  ];

  return (
    <div className="w-full h-16 card-panel flex items-center justify-between px-6 mb-6 shrink-0">
      <div className="flex min-w-0 items-center gap-8">
        <Link href="/" className="shrink-0 font-heading font-bold text-xl text-[var(--color-primary)] tracking-wide">
          UrbanOS <span className="text-slate-500 font-normal">CITY INTELLIGENCE</span>
        </Link>
        <nav className="hidden md:flex shrink-0 gap-6 text-sm font-semibold tracking-wider">
          {navItems.map((item) => {
            const isActive = pathname === item.path;
            return (
              <Link 
                key={item.path} 
                href={item.path}
                className={`${isActive ? 'text-slate-900 border-b-2 border-[var(--color-primary)] pb-1' : 'text-slate-500 hover:text-slate-900 transition-colors'}`}
              >
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center space-x-6">
        <div className="flex items-center space-x-2 text-slate-500 text-sm font-mono">
          <Clock size={16} />
          <span>{currentTime}</span>
        </div>
      </div>
    </div>
  );
}
