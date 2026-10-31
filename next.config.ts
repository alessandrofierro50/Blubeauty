import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Build autonoma per l'immagine Docker (vedi Dockerfile)
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
