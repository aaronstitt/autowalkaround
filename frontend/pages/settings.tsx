import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import { onboarding } from '../lib/api';
import { Plus, Trash2, ArrowLeft, User, Video, CheckCircle, AlertCircle } from 'lucide-react';

export default function Settings() {
  const router = useRouter();
  const [salespersons, setSalespersons] = useState<any[]>([]);
  const [avatars, setAvatars] = useState<any[]>([]);
  const [voices, setVoices] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ name:'', heygen_avatar_id:'', heygen_voice_id:'', lot_background_url:'' });
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [sourceVideoUrls, setSourceVideoUrls] = useState<Record<string, string>>({});
  const [savingVideo, setSavingVideo] = useState<Record<string, boolean>>({});
  const [videoSaveStatus, setVideoSaveStatus] = useState<Record<string, string>>({});
  const set = (k: string) => (e: any) => setForm(f => ({...f, [k]: e.target.value}));

  useEffect(() => { loadAll(); }, []);

  async function loadAll() {
    try {
      const [sps, avs, vs] = await Promise.all([
        onboarding.getSalespersons(),
        onboarding.getAvatars().catch(() => []),
        onboarding.getVoices().catch(() => [])
      ]);
      setSalespersons(sps);
      setAvatars(avs);
      setVoices(vs.slice(0, 50));
      // Pre-populate source video URL fields
      const urls: Record<string, string> = {};
      sps.forEach((sp: any) => { if (sp.source_video_url) urls[sp.id] = sp.source_video_url; });
      setSourceVideoUrls(urls);
    } catch(e) { router.push('/login'); }
  }

  async function addSalesperson(e: any) {
    e.preventDefault();
    setLoading(true); setError(''); setSuccess('');
    try {
      await onboarding.addSalesperson(form);
      setForm({ name:'', heygen_avatar_id:'', heygen_voice_id:'', lot_background_url:'' });
      setSuccess('Salesperson added successfully!');
      loadAll();
    } catch(err: any) {
      setError(err.response?.data?.detail || 'Failed to add salesperson');
    } finally { setLoading(false); }
  }

  async function removeSp(id: string) {
    if (!confirm('Remove this salesperson?')) return;
    await onboarding.deleteSalesperson(id);
    loadAll();
  }

  async function saveSourceVideo(spId: string) {
    const url = sourceVideoUrls[spId] || '';
    if (!url.trim()) return;
    setSavingVideo(prev => ({...prev, [spId]: true}));
    setVideoSaveStatus(prev => ({...prev, [spId]: ''}));
    try {
      const token = localStorage.getItem('token');
      const apiUrl = process.env.NEXT_PUBLIC_API_URL;
      const resp = await fetch(`${apiUrl}/onboarding/salespersons/${spId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ source_video_url: url.trim() })
      });
      if (resp.ok) {
        setVideoSaveStatus(prev => ({...prev, [spId]: 'saved'}));
      } else {
        const err = await resp.json();
        setVideoSaveStatus(prev => ({...prev, [spId]: 'error: ' + (err.detail || 'failed')}));
      }
    } catch(err: any) {
      setVideoSaveStatus(prev => ({...prev, [spId]: 'error: ' + err.message}));
    } finally {
      setSavingVideo(prev => ({...prev, [spId]: false}));
    }
  }

  return (
    <div className='min-h-screen'>
      <header className='border-b border-gray-800 px-6 py-4 flex items-center gap-4'>
        <button onClick={() => router.push('/dashboard')} className='text-gray-400 hover:text-white transition-colors'>
          <ArrowLeft className='w-5 h-5' />
        </button>
        <h1 className='text-2xl font-bold'>Settings</h1>
      </header>

      <main className='max-w-3xl mx-auto px-6 py-8 space-y-8'>
        {/* Current Salespersons */}
        <div className='card'>
          <h2 className='text-xl font-bold mb-6 flex items-center gap-2'><User className='w-5 h-5 text-brand' />Salespersons</h2>
          {salespersons.length === 0 ? (
            <p className='text-gray-500 text-sm'>No salespersons added yet.</p>
          ) : (
            <div className='space-y-4'>
              {salespersons.map(sp => (
                <div key={sp.id} className='p-4 bg-gray-800 rounded-xl space-y-3'>
                  <div className='flex items-center gap-4'>
                    <div className='w-10 h-10 bg-brand/20 rounded-full flex items-center justify-center text-brand font-bold flex-shrink-0'>{sp.name[0]}</div>
                    <div className='flex-1'>
                      <p className='font-medium'>{sp.name}</p>
                      <p className='text-xs text-gray-500'>Avatar: {sp.heygen_avatar_id?.slice(0,12)}...</p>
                    </div>
                    <button onClick={() => removeSp(sp.id)} className='text-red-400 hover:text-red-300 transition-colors flex-shrink-0'><Trash2 className='w-4 h-4' /></button>
                  </div>
                  {/* Walkaround Source Video URL */}
                  <div className='border-t border-gray-700 pt-3'>
                    <label className='block text-xs font-medium text-gray-400 mb-1 flex items-center gap-1'>
                      <Video className='w-3 h-3' /> Walkaround Source Video URL
                      {!sp.source_video_url && !sourceVideoUrls[sp.id] && (
                        <span className='ml-1 text-yellow-400 text-xs'>⚠ Required to generate videos</span>
                      )}
                    </label>
                    <div className='flex gap-2'>
                      <input
                        className='input flex-1 text-sm py-2'
                        type='url'
                        value={sourceVideoUrls[sp.id] || ''}
                        onChange={e => setSourceVideoUrls(prev => ({...prev, [sp.id]: e.target.value}))}
                        placeholder='https://... direct link to your walkaround recording MP4'
                      />
                      <button
                        onClick={() => saveSourceVideo(sp.id)}
                        disabled={savingVideo[sp.id] || !sourceVideoUrls[sp.id]}
                        className='px-3 py-2 bg-brand text-white rounded-xl text-sm font-medium hover:bg-brand/80 disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0 transition-colors'
                      >
                        {savingVideo[sp.id] ? 'Saving...' : 'Save'}
                      </button>
                    </div>
                    {videoSaveStatus[sp.id] === 'saved' && (
                      <p className='text-xs text-green-400 mt-1 flex items-center gap-1'><CheckCircle className='w-3 h-3' /> Saved! Videos will now use this walkaround recording.</p>
                    )}
                    {videoSaveStatus[sp.id]?.startsWith('error') && (
                      <p className='text-xs text-red-400 mt-1 flex items-center gap-1'><AlertCircle className='w-3 h-3' /> {videoSaveStatus[sp.id]}</p>
                    )}
                    <p className='text-xs text-gray-600 mt-1'>Paste the direct URL to your walkaround video recording (Supabase, Google Drive direct link, etc.)</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Add Salesperson Form */}
        <div className='card'>
          <h2 className='text-xl font-bold mb-2 flex items-center gap-2'><Plus className='w-5 h-5 text-brand' />Add Salesperson</h2>
          <p className='text-gray-400 text-sm mb-6'>You need to have already created an avatar and cloned a voice in HeyGen, then paste their IDs here.</p>
          {error && <div className='bg-red-900/50 border border-red-500 text-red-300 px-4 py-3 rounded-xl mb-4 text-sm'>{error}</div>}
          {success && <div className='bg-green-900/50 border border-green-500 text-green-300 px-4 py-3 rounded-xl mb-4 text-sm'>{success}</div>}
          <form onSubmit={addSalesperson} className='space-y-4'>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Salesperson Name *</label>
              <input className='input' value={form.name} onChange={set('name')} required placeholder='John Smith' />
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>HeyGen Avatar ID *</label>
              <input className='input' value={form.heygen_avatar_id} onChange={set('heygen_avatar_id')} required placeholder='Paste from HeyGen dashboard' />
              <p className='text-xs text-gray-500 mt-1'>Find this in HeyGen → Avatars → your custom avatar → copy ID</p>
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>HeyGen Voice ID *</label>
              <input className='input' value={form.heygen_voice_id} onChange={set('heygen_voice_id')} required placeholder='Paste from HeyGen dashboard' />
              <p className='text-xs text-gray-500 mt-1'>Find this in HeyGen → Voices → your cloned voice → copy ID</p>
            </div>
            <div>
              <label className='block text-sm font-medium text-gray-400 mb-1'>Lot Background Image URL (optional)</label>
              <input className='input' value={form.lot_background_url} onChange={set('lot_background_url')} placeholder='https://your-cdn.com/lot-photo.jpg' />
              <p className='text-xs text-gray-500 mt-1'>Upload a photo of your dealership lot somewhere (Google Drive, Imgur, etc.) and paste the direct link</p>
            </div>
            <button type='submit' className='btn-primary w-full' disabled={loading}>
              {loading ? 'Adding...' : 'Add Salesperson'}
            </button>
          </form>
        </div>

        {/* Instructions */}
        <div className='card border-brand/30'>
          <h2 className='text-lg font-bold mb-4 text-brand'>How to get HeyGen IDs</h2>
          <ol className='space-y-3 text-sm text-gray-300 list-decimal list-inside'>
            <li>Sign up at <strong>heygen.com</strong></li>
            <li>Go to <strong>Avatars → Create Avatar</strong> and upload the salesperson video</li>
            <li>Once trained, click the avatar and copy the <strong>Avatar ID</strong></li>
            <li>Go to <strong>Voices → Clone Voice</strong> and upload the 2-minute voice sample</li>
            <li>Once cloned, copy the <strong>Voice ID</strong></li>
            <li>Paste both IDs above and click Add Salesperson</li>
            <li>After adding, paste the <strong>Walkaround Source Video URL</strong> in the salesperson card above and click Save</li>
          </ol>
        </div>
      </main>
    </div>
  );
}