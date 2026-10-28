"use client";

/**
 * Placeholder for a route that is not built yet, using the shared light card.
 */

export default function ComingSoon({
  title = "Coming Soon",
  domain,
}: {
  title?: string;
  /** Domain id retained as placeholder metadata. */
  domain?: string;
}) {
  return (
    <div className="flex h-[calc(100vh-4rem)] items-center justify-center bg-background px-8">
      <div
        className="card-panel border border-line text-ink p-10 text-center"
        data-testid="coming-soon"
        data-domain={domain}
      >
        <div className="absolute inset-0 card-pattern opacity-30" aria-hidden="true" />
        <div className="relative z-10">
          <h1 className="text-3xl font-heading font-bold text-ink mb-3">{title}</h1>
          <p className="text-sm text-ink-soft">
            This module is under development and will be available soon.
          </p>
        </div>
      </div>
    </div>
  );
}
