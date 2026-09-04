"use client";

export default function ComingSoon({ title = "Coming Soon" }: { title?: string }) {
  return (
    <div className="flex h-[calc(100vh-4rem)] items-center justify-center bg-slate-950 text-slate-300 px-8">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-slate-100 mb-4">{title}</h1>
        <p className="text-lg text-slate-400">
          This module is under development and will be available soon.
        </p>
      </div>
    </div>
  );
}