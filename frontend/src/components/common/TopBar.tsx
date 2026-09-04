"use client";

import { Activity, Clock } from 'lucide-react';
import { format } from 'date-fns';
import { useState, useEffect } from 'react';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

export default function TopBar() {
  const [currentTime, setCurrentTime] = useState<string>('');
  const pathname = usePathname();

  useEffect(() => {
    // Use a small initial delay if we don't want a flash, but setting state directly in effect is frowned upon.
    // Instead we can just let the interval run.
    const interval = setInterval(() => {
      setCurrentTime(format(new Date(), 'HH:mm:ss | dd MMM yyyy'));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const navItems = [
    { name: 'OVERVIEW', path: '/' },
    { name: 'WEATHER', path: '/weather' },
    { name: 'POLLUTION', path: '/pollution' },
    { name: 'FLOOD', path: '/flood' },
    { name: 'TRAFFIC', path: '/traffic' },
  ];

  return (
    <div className="w-full h-16 glass-panel flex items-center justify-between px-6 mb-6 shrink-0">
      <div className="flex items-center space-x-8">
        <Link href="/" className="font-heading font-bold text-xl text-[var(--color-primary)] tracking-wide">
          UrbanOS <span className="text-gray-400 font-normal">CITY INTELLIGENCE</span>
        </Link>
        <nav className="hidden md:flex space-x-6 text-sm font-semibold tracking-wider">
          {navItems.map((item) => {
            const isActive = pathname === item.path;
            return (
              <Link 
                key={item.path} 
                href={item.path}
                className={`${isActive ? 'text-white border-b-2 border-[var(--color-primary)] pb-1' : 'text-gray-400 hover:text-white transition-colors'}`}
              >
                {item.name}
              </Link>
            );
          })}
        </nav>
      </div>
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
  );
}
