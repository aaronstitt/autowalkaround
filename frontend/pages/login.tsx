import { useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { auth } from '../lib/api';

export default function Login() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: any) {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      const data = await auth.login({ email, password });
      localStorage.setItem('token', data.token);
      router.push('/dashboard');
    } catch(err: any) {
      setError(err.response?.data?.detail || 'Login failed');
    } finally { setLoading(false); }
  }

  return (
    <div className='min-h-screen flex items-center justify-center p-4'>
      <div className='w-full max-w-md'>
        <div className='text-center mb-8'>
          <h1 className='text-4xl font-bold mb-2'>🎬 AutoWalkaround</h1>
          <p className='text-gray-400'>AI-powered vehicle walkthrough videos</p>
        </div>
        <div className='card'>
          <h2 className='text-2xl font-bold mb-6'>Sign In</h2>
          {error && <div className='bg-red-900/50 border border-red-500 text-red-300 px-4 py-3 rounded-xl mb-4'>{error}</div>}
          <form onSubmit={handleLogin} className='space-y-4'>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Email</label>
              <input className='input' type='email' value={email} onChange={e => setEmail(e.target.value)} required placeholder='you@dealership.com' />
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Password</label>
              <input className='input' type='password' value={password} onChange={e => setPassword(e.target.value)} required placeholder='••••••••' />
            </div>
            <button type='submit' className='btn-primary w-full' disabled={loading}>
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>
          <p className='text-center text-gray-500 mt-4 text-sm'>
            Don't have an account? <Link href='/signup' className='text-brand hover:underline'>Sign up</Link>
          </p>
        </div>
      </div>
    </div>
  );
}