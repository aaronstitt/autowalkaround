# 🎬 AutoWalkaround

AI-powered vehicle walkaround video generator for car dealerships.

Paste any vehicle listing URL → get a 90-second MP4 of your salesperson walking around and talking about the car.

## Architecture
- **Frontend**: Next.js + Tailwind CSS (deployed on Vercel)
- **Backend**: Python FastAPI (deployed on Railway)
- **Database**: Supabase (PostgreSQL)
- **AI Script**: OpenAI GPT-4o-mini
- **Avatar Video**: HeyGen API
- **Video Assembly**: FFmpeg

## Setup Guide

### 1. Database (Supabase)
1. Create account at supabase.com
2. Create new project
3. Go to SQL Editor and run `database/schema.sql`
4. Go to Settings → API and copy your URL and keys

### 2. Backend (Railway)
1. Create account at railway.app
2. New Project → Deploy from GitHub → select this repo
3. Set root directory to `backend`
4. Add environment variables (see backend/.env.example)
5. Deploy — copy the public URL

### 3. Frontend (Vercel)
1. Create account at vercel.com
2. New Project → Import from GitHub → select this repo
3. Set root directory to `frontend`
4. Add environment variable: `NEXT_PUBLIC_API_URL` = your Railway backend URL
5. Deploy

### 4. HeyGen Setup (per salesperson)
1. Sign up at heygen.com
2. Avatars → Create Avatar → upload salesperson gesturing video
3. Voices → Clone Voice → upload 2-min speech sample
4. Copy Avatar ID and Voice ID
5. Add in the app: Settings → Add Salesperson

## Pricing Tiers (future Stripe integration)
- Starter: 30 videos/month - $149
- Growth: 90 videos/month - $359
- Unlimited: $599/month