/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep local validation from generating unrelated AGENTS.md files.
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

  allowedDevOrigins: ['127.0.0.1', '192.168.0.216'],

  experimental: {
    optimizePackageImports: ["@chakra-ui/react"],
  },

  reactCompiler: true,
};

export default nextConfig;
