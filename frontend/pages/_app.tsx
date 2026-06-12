import type { AppProps } from 'next/app';
import '../styles/globals.css';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/router';

const PUBLIC_ROUTES = ['/', '/login', '/signup'];

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem('token');
    const isPublic = PUBLIC_ROUTES.includes(router.pathname);
    if (!token && !isPublic) { router.push('/login'); }
    else { setReady(true); }
  }, [router.pathname]);

  if (!ready) return <div className='min-h-screen bg-gray-950 flex items-center justify-center'><div className='text-white text-xl'>Loading...</div></div>;
  return <Component {...pageProps} />;
}