import { useEffect } from 'react';

// Cloudflare Web Analytics — privacy-respecting, cookie-less,
// GDPR/CCPA-friendly. Only loads when the build is configured with a
// site token via `VITE_CF_ANALYTICS_TOKEN`.
//
// To enable:
//   1. Create a free site at https://dash.cloudflare.com/?to=/:account/web-analytics
//   2. Copy the site token from the snippet Cloudflare gives you
//   3. Set the env var when building:
//        VITE_CF_ANALYTICS_TOKEN=<token> npm run build
//      or in `.env.production`:
//        VITE_CF_ANALYTICS_TOKEN=<token>
//
// In dev (`npm run dev`) the token is unset and this component is a
// no-op, so analytics never fires while you're working locally.

const TOKEN = import.meta.env.VITE_CF_ANALYTICS_TOKEN as string | undefined;

export function CloudflareAnalytics() {
  useEffect(() => {
    if (!TOKEN) return;
    if (document.querySelector('script[data-cf-beacon]')) return; // dedupe

    const script = document.createElement('script');
    script.defer = true;
    script.src = 'https://static.cloudflareinsights.com/beacon.min.js';
    script.setAttribute('data-cf-beacon', JSON.stringify({ token: TOKEN, spa: true }));
    document.head.appendChild(script);

    return () => {
      // Don't remove on unmount — analytics should persist for the
      // lifetime of the page. The dedupe guard above handles HMR.
    };
  }, []);

  return null;
}
