import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: {
    position: 'bottom-right'
  },
  output: 'standalone',
  // The npm project lives in frontend/, but a stray root package-lock.json makes
  // Next.js infer C:\projects\UrbanOS as the workspace root. Pin it explicitly
  // so module resolution and file watching are deterministic.
  turbopack: {
    root: path.resolve(__dirname),
  },
};

export default nextConfig;