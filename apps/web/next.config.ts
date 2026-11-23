import type { NextConfig } from "next";

// NourishRelay web app configuration.
// - `output: "standalone"` produces a self-contained server for the runtime
//   stage of the Docker image (see apps/web/Dockerfile).
// - React strict mode surfaces state bugs early.
const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
