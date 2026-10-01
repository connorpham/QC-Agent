import type { NextConfig } from "next";

// Same-origin API: the browser calls /api/... on this host and Next proxies it to the backend,
// so the HttpOnly session cookie is a first-party cookie. Read at BUILD time.
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
