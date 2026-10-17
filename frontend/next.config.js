/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow the backend API to be proxied during local development so the
  // frontend can call /api/v1/... without CORS issues when running
  // `npm run dev` (Next.js dev server on :3000, backend on :8000).
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
    ];
  },

  // Strict React mode catches double-invocation bugs early.
  reactStrictMode: true,
};

export default nextConfig;
