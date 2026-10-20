"use client";

/**
 * Placeholder for a route that is not built yet.
 *
 * Still themed: the card carries the domain's solid colour so these routes read
 * as part of the same system rather than as an unfinished corner of the app.
 */
import { domainFill } from "@/components/city/presentation";

export default function ComingSoon({
  title = "Coming Soon",
  domain,
}: {
  title?: string;
  /** Domain id, so the placeholder matches the colour of the real page. */
  domain?: string;
}) {
  return (
    <div className="flex h-[calc(100vh-4rem)] items-center justify-center bg-[#f1f5f9] px-8">
      <div
        className={`solid-card ${domainFill(domain)} p-10 text-center`}
        data-testid="coming-soon"
        data-domain={domain}
      >
        <div className="absolute inset-0 card-pattern opacity-30" aria-hidden="true" />
        <div className="relative z-10">
          <h1 className="text-3xl font-heading font-bold text-white mb-3">{title}</h1>
          <p className="text-sm text-white/90">
            This module is under development and will be available soon.
          </p>
        </div>
      </div>
    </div>
  );
}