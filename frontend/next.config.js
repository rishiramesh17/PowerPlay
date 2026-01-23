/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    // Works both locally and on Vast because frontend + backend run in same machine/container
    const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

    return [
      { source: "/api/:path*", destination: `${backend}/:path*` },

      // proxy video file serving too (so <video src="/outputs/..."> works)
      { source: "/outputs/:path*", destination: `${backend}/outputs/:path*` },
      { source: "/uploads/:path*", destination: `${backend}/uploads/:path*` },
      { source: "/downloads/:path*", destination: `${backend}/downloads/:path*` },
    ];
  },
};

module.exports = nextConfig;