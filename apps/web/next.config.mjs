/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The console talks to the API through a same-origin rewrite so that browser
  // requests carry cookies without a CORS preflight on every call.
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.BACKSTOP_API_URL ?? 'http://localhost:8000'}/:path*`,
      },
    ]
  },
}

export default nextConfig
