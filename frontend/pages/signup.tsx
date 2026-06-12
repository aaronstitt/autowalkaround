import { useState } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { auth } from '../lib/api';

export default function Signup() {
  const router = useRouter();
  const [form, setForm] = useState({ email:'', password:'', dealership_name:'', contact_name:'', website_url:'' });
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const set = (k: string) => (e: any) => setForm(f => ({...f, [k]: e.target.value}));

  async function handleSignup(e: any) {
    e.preventDefault();
    setLoading(true); setError('');
    try {
      const data = await auth.signup(form);
      localStorage.setItem('token', data.token);
      router.push('/onboarding');
    } catch(err: any) {
      setError(err.response?.data?.detail || 'Signup failed');
    } finally { setLoading(false); }
  }

  return (
    <div className='min-h-screen flex items-center justify-center p-4'>
      <div className='w-full max-w-md'>
        <div className='text-center mb-8'>
          <h1 className='text-4xl font-bold mb-2'>🎬 AutoWalkaround</h1>
          <p className='text-gray-400'>Create your dealership account</p>
        </div>
        <div className='card'>
          <h2 className='text-2xl font-bold mb-6'>Create Account</h2>
          {error && <div className='bg-red-900/50 border border-red-500 text-red-300 px-4 py-3 rounded-xl mb-4'>{error}</div>}
          <form onSubmit={handleSignup} className='space-y-4'>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Dealership Name *</label>
              <input className='input' value={form.dealership_name} onChange={set('dealership_name')} required placeholder='Immaculate Used Cars' />
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Your Name</label>
              <input className='input' value={form.contact_name} onChange={set('contact_name')} placeholder='Aaron Stitt' />
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Dealership Website</label>
              <input className='input' value={form.website_url} onChange={set('website_url')} placeholder='https://www.immaculateusedcars.com' />
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Email *</label>
              <input className='input' type='email' value={form.email} onChange={set('email')} required placeholder='you@dealership.com' />
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Password *</label>
              <input className='input' type='password' value={form.password} onChange={set('password')} required placeholder='Min 8 characters' minLength={8} />
            </div>
            <button type='submit' className='btn-primary w-full' disabled={loading}>
              {loading ? 'Creating account...' : 'Create Account & Get Started'}
            </button>
          </form>
          <p className='text-center text-gray-500 mt-4 text-sm'>
            Already have an account? <Link href='/login' className='text-brand hover:underline'>Sign in</Link>
          </p>
        </div>
      </div>
    </div>
  );
}