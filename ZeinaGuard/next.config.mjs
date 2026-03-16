/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: {
    appIsrStatus: false,
    buildActivity: false,
    buildActivityPosition: 'bottom-right',
  },
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  allowedDevOrigins: ["*.replit.dev", "*.replit.app", "*.janeway.replit.dev"],
  async rewrites() {
    const target = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
    return [
      { source: '/backend-api/:path*', destination: `${target}/:path*` },
    ];
  },
}

export default nextConfig
