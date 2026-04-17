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
    // Use BACKEND_URL (server-side only env var) if available, 
    // otherwise fallback to NEXT_PUBLIC_API_URL or localhost
    const target = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:5000';
    
    // Safety check: if target is a relative path (like '/backend-api'), fallback to localhost
    const finalTarget = target.startsWith('http') ? target : 'http://localhost:5000';
    
    return [
      { source: '/backend-api/:path*', destination: `${finalTarget}/:path*` },
    ];
  },
}

export default nextConfig
