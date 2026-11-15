/** @type {import('next').NextConfig} */
const zap = process.env.DAM_ZAP_FRONTEND === '1';
if (zap && (process.env.NEXT_PUBLIC_API_URL !== 'https://127.0.0.2:8443' || process.env.NEXT_PUBLIC_ZAP !== '1')) {
  throw new Error('ZAP frontend requires the dedicated isolated API.');
}
// Opt in at build or start only when Next.js or its trusted proxy serves HTTPS
// NODE_ENV=production alone does not establish HTTPS. ZAP uses local TLS
const enableHsts = zap || process.env.FRONTEND_HTTPS === 'true';
const nextConfig = {
  // Keep local validation from generating unrelated AGENTS.md files
  agentRules: false,
  /* config options here */
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: '127.0.0.1',
        port: '8000',
        pathname: '/media/uploads/**'
      },
    ],
  },

  allowedDevOrigins: zap ? ['127.0.0.2'] : ['127.0.0.1', '192.168.0.216'],
  async headers() {
    const headers = [{ key: 'X-Content-Type-Options', value: 'nosniff' }];
    if (enableHsts) {
      // Limit the policy to this host, no subdomain or preload commitment
      headers.push({ key: 'Strict-Transport-Security', value: 'max-age=31536000' });
    }
    if (zap) {
      // Prevent browser integrations from contacting services outside this disposable app
      headers.push(
        { key: 'Content-Security-Policy', value: "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https://127.0.0.2:8443; media-src 'self' blob: https://127.0.0.2:8443; connect-src 'self' https://127.0.0.2:8443 wss://127.0.0.2:3443; frame-src 'self' https://127.0.0.2:8443; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self' https://127.0.0.2:8443" },
        { key: 'X-DAM-Environment', value: 'disposable-zap' },
      );
    }
    return [{ source: '/:path*', headers }];
  },

  experimental: {
    optimizePackageImports: ["@chakra-ui/react"],
  },

  reactCompiler: true,
};

export default nextConfig;
