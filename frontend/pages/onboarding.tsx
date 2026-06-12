import { useRouter } from 'next/router';
import { CheckCircle, Video, Settings } from 'lucide-react';

export default function Onboarding() {
  const router = useRouter();
  return (
    <div className='min-h-screen flex items-center justify-center p-4'>
      <div className='max-w-lg w-full text-center'>
        <CheckCircle className='w-16 h-16 text-green-400 mx-auto mb-6' />
        <h1 className='text-3xl font-bold mb-4'>Account Created!</h1>
        <p className='text-gray-400 mb-8'>Welcome to AutoWalkaround. Before generating your first video, you need to add at least one salesperson with their HeyGen avatar and voice.</p>
        <div className='card mb-6 text-left'>
          <h2 className='font-bold mb-4 text-lg'>Next Steps:</h2>
          <ol className='space-y-3 text-sm text-gray-300 list-decimal list-inside'>
            <li>Record the salesperson videos (see instructions on Settings page)</li>
            <li>Create an avatar in HeyGen using their gesturing video</li>
            <li>Clone their voice in HeyGen using the 2-min speech sample</li>
            <li>Add the salesperson in Settings with the HeyGen IDs</li>
            <li>Start generating walkaround videos!</li>
          </ol>
        </div>
        <div className='flex gap-4'>
          <button onClick={() => router.push('/settings')} className='btn-primary flex-1 flex items-center justify-center gap-2'>
            <Settings className='w-4 h-4' />Go to Settings
          </button>
          <button onClick={() => router.push('/dashboard')} className='flex-1 bg-gray-800 text-white font-semibold px-6 py-3 rounded-xl hover:bg-gray-700 transition-colors flex items-center justify-center gap-2'>
            <Video className='w-4 h-4' />Go to Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}