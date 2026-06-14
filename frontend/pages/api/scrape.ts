import type { NextApiRequest, NextApiResponse } from 'next';

export const config = {
  api: {
    responseLimit: '10mb',
  },
};

export default async function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { url } = req.body;
  if (!url || typeof url !== 'string') {
    return res.status(400).json({ error: 'URL is required' });
  }

  // Only allow immaculateusedcars.com to prevent abuse
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.endsWith('immaculateusedcars.com')) {
      return res.status(403).json({ error: 'Only immaculateusedcars.com URLs are supported' });
    }
  } catch {
    return res.status(400).json({ error: 'Invalid URL' });
  }

  try {
    const response = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Cache-Control': 'no-cache',
      },
    });

    if (!response.ok) {
      return res.status(response.status).json({ error: `Upstream returned ${response.status}` });
    }

    const html = await response.text();
    res.setHeader('Content-Type', 'application/json');
    return res.status(200).json({ html });
  } catch (err: any) {
    return res.status(500).json({ error: err.message || 'Failed to fetch page' });
  }
}
