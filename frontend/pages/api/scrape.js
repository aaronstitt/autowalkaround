// Vercel serverless API route: /api/scrape
// Fetches vehicle listing HTML server-side using ScraperAPI to avoid CORS + bot detection
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { url } = req.body || {};
  if (!url) {
    return res.status(400).json({ error: 'Missing url parameter' });
  }

  // Validate it's an immaculateusedcars.com URL
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.includes('immaculateusedcars.com') &&
        !parsed.hostname.includes('dealer.com')) {
      return res.status(400).json({ error: 'URL must be from immaculateusedcars.com' });
    }
  } catch (e) {
    return res.status(400).json({ error: 'Invalid URL' });
  }

  const SCRAPER_API_KEY = process.env.SCRAPER_API_KEY || 'd5c33c8f1fbebda2f3404132af42107c';

  try {
    // Try ScraperAPI first
    const scraperUrl = `http://api.scraperapi.com?api_key=${SCRAPER_API_KEY}&url=${encodeURIComponent(url)}&render=true`;
    const response = await fetch(scraperUrl, {
      method: 'GET',
      headers: { 'Accept': 'text/html' },
      signal: AbortSignal.timeout(25000),
    });

    if (!response.ok) {
      throw new Error(`ScraperAPI returned ${response.status}`);
    }

    const html = await response.text();
    if (!html || html.length < 1000) {
      throw new Error('ScraperAPI returned empty or too-short HTML');
    }

    return res.status(200).json({ html, source: 'scraperapi' });

  } catch (scraperErr) {
    console.warn('ScraperAPI failed:', scraperErr.message);

    // Fallback: direct fetch with browser-like headers
    try {
      const directResp = await fetch(url, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
          'Accept-Language': 'en-US,en;q=0.9',
          'Cache-Control': 'no-cache',
        },
        signal: AbortSignal.timeout(15000),
      });

      if (!directResp.ok) {
        throw new Error(`Direct fetch returned ${directResp.status}`);
      }

      const html = await directResp.text();
      return res.status(200).json({ html, source: 'direct' });

    } catch (directErr) {
      console.error('Both scrape methods failed:', directErr.message);
      // Return empty html — backend will attempt its own scrape
      return res.status(200).json({ html: '', source: 'failed', error: directErr.message });
    }
  }
}

export const config = {
  api: {
    bodyParser: {
      sizeLimit: '2mb',
    },
    responseLimit: '8mb',
  },
};
