/**
 * The browser only ever talks to this origin; /api is proxied to FastAPI.
 * SONICDNA_API_URL is read when `next build` runs (rewrites are fixed at build time).
 */
const apiUrl = process.env.SONICDNA_API_URL || "http://127.0.0.1:8000";

export default {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};
