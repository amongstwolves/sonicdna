/**
 * The browser only ever talks to this origin.
 * Local: /api is proxied to FastAPI. SONICDNA_API_URL is read when `next build` runs.
 * SONICDNA_EXPORT=1: a static export that FastAPI serves itself, so no proxy is needed.
 */
const apiUrl = process.env.SONICDNA_API_URL || "http://127.0.0.1:8000";

const exported = { reactStrictMode: true, output: "export", trailingSlash: true };

const proxied = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default process.env.SONICDNA_EXPORT === "1" ? exported : proxied;
