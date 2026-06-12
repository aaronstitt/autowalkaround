-- Run this in Supabase SQL Editor

create table if not exists dealerships (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  website_url text default '',
  lot_background_url text default '',
  plan text default 'free',
  videos_generated_this_month integer default 0,
  created_at timestamptz default now()
);

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  password_hash text not null,
  dealership_id uuid references dealerships(id),
  contact_name text default '',
  role text default 'admin',
  created_at timestamptz default now()
);

create table if not exists salespersons (
  id uuid primary key default gen_random_uuid(),
  dealership_id uuid references dealerships(id),
  name text not null,
  heygen_avatar_id text not null,
  heygen_voice_id text not null,
  lot_background_url text default '',
  created_at timestamptz default now()
);

create table if not exists video_jobs (
  id uuid primary key,
  dealership_id uuid references dealerships(id),
  user_id uuid references users(id),
  salesperson_id uuid references salespersons(id),
  vehicle_url text not null,
  vehicle_name text default '',
  vehicle_vin text default '',
  status text default 'queued',
  status_message text default '',
  script text default '',
  output_path text default '',
  created_at timestamptz default now()
);

-- Reset monthly video counts (run via cron or Supabase scheduled function on 1st of month)
-- UPDATE dealerships SET videos_generated_this_month = 0;