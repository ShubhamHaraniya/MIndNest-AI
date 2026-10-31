// The browser only ever talks to this origin. Requests to /api/* are forwarded to the FastAPI
// service, so the session cookie is first-party (no CORS, no cross-site cookie rules).
// The destination is read when `next build` / `next dev` starts: set API_INTERNAL_URL before then.
const apiInternalUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Compression would buffer the streamed chat answers until they finish.
  compress: false,
  experimental: {
    // Rewrites time out after 30 s by default, which is too short for a long answer.
    proxyTimeout: 180_000,
  },
  async headers() {
    // Browser-side limits that hold even if something unsafe reaches a page: no framing, no
    // plug-ins, no pictures from other sites (they can carry data out), same-site form posts only.
    const headers = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "DENY" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
      {
        key: "Content-Security-Policy",
        value:
          "default-src 'self'; img-src 'self' data: blob:; object-src 'none'; base-uri 'self'; " +
          "frame-ancestors 'none'; form-action 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; " +
          "style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'",
      },
    ];
    // A file the student opens in the preview pane is framed by our own pages, so its response is
    // the one place that may be framed (by this site only); every other path stays unframeable.
    // (Its CSP is only the framing rule: a page-style CSP with object-src 'none' stops Chrome's
    // built-in PDF viewer from drawing the file.)
    const framable = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "X-Frame-Options", value: "SAMEORIGIN" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "Content-Security-Policy", value: "frame-ancestors 'self'" },
    ];
    return [
      { source: "/api/v1/materials/:id/download", headers: framable },
      { source: "/api/v1/library/:id/file", headers: framable },
      { source: "/((?!api/v1/materials/[^/]+/download|api/v1/library/[^/]+/file).*)", headers },
    ];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` }];
  },
};

export default nextConfig;
