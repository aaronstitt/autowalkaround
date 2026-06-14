import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/router';
import { video, onboarding, auth } from '../lib/api';
import { Video, Plus, Download, Clock, CheckCircle, XCircle, Loader, LogOut, Settings } from 'lucide-react';

const STATUS_ICONS: any = {
  queued: <Clock className='w-5 h-5 text-yellow-400' />,
  scraping: <Loader className='w-5 h-5 text-blue-400 animate-spin' />,
  scripting: <Loader className='w-5 h-5 text-blue-400 animate-spin' />,
  rendering: <Loader className='w-5 h-5 text-purple-400 animate-spin' />,
  assembling: <Loader className='w-5 h-5 text-purple-400 animate-spin' />,
  completed: <CheckCircle className='w-5 h-5 text-green-400' />,
  failed: <XCircle className='w-5 h-5 text-red-400' />,
};

export default function Dashboard() {
  const router = useRouter();
  const [user, setUser] = useState<any>(null);
  const [salespersons, setSalespersons] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [vehicleUrl, setVehicleUrl] = useState('');
  const [selectedSp, setSelectedSp] = useState('');
  const [generating, setGenerating] = useState(false);
  const [activeJob, setActiveJob] = useState<any>(null);
  const [error, setError] = useState('');
  const pollRef = useRef<any>(null);

  useEffect(() => {
    loadData();
    return () => clearInterval(pollRef.current);
  }, []);

  async function loadData() {
    try {
      const [me, sps, history] = await Promise.all([auth.me(), onboarding.getSalespersons(), video.history()]);
      setUser(me);
      setSalespersons(sps);
      setJobs(history);
      if (sps.length > 0) setSelectedSp(sps[0].id);
    } catch(e) { router.push('/login'); }
  }

  async function handleGenerate(e: any) {
    e.preventDefault();
    if (!vehicleUrl || !selectedSp) return;
    setGenerating(true); setError('');
    try {
      // Use Vercel API route to fetch vehicle page HTML server-side (avoids CORS + bot detection)
      let pageHtml: string | undefined;
      try {
        const scrapeResp = await fetch('/api/scrape', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: vehicleUrl }),
        });
        if (scrapeResp.ok) {
          const scrapeData = await scrapeResp.json();
          pageHtml = scrapeData.html;
        }
      } catch(fetchErr) {
        // If Vercel scrape fails, backend will try server-side
        console.warn('Vercel scrape failed, backend will retry:', fetchErr);
      }

      const job = await video.generate({ vehicle_url: vehicleUrl, salesperson_id: selectedSp, page_html: pageHtml });
      setActiveJob(job);
      setVehicleUrl('');
      pollRef.current = setInterval(() => pollJob(job.job_id), 8000);
      loadData();
    } catch(err: any) {
      setError(err.response?.data?.detail || 'Generation failed');
    } finally { setGenerating(false); }
  }

  async function pollJob(jobId: string) {
    try {
      const status = await video.status(jobId);
      setJobs(prev => prev.map(j => j.id === jobId ? status : j));
      if (status.status === 'completed' || status.status === 'failed') {
        clearInterval(pollRef.current);
        setActiveJob(null);
        loadData();
      }
    } catch(e) {}
  }

  function handleDownload(jobId: string, vehicleName: string) {
    const token = localStorage.getItem('token');
    const url = `${process.env.NEXT_PUBLIC_API_URL}/video/download/${jobId}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `${vehicleName || 'walkaround'}.mp4`;
    document.head.appendChild(a);
    a.click();
    document.head.removeChild(a);
  }

  function logout() {
    localStorage.removeItem('token');
    router.push('/login');
  }

  const dealership = user?.dealerships;

  return (
    <div className='min-h-screen'>
      {/* Header */}
      <header className='border-b border-gray-800 px-6 py-4 flex items-center justify-between'>
        <h1 className='text-2xl font-bold'>🎬 AutoWalkaround</h1>
        <div className='flex items-center gap-4'>
          {dealership && <span className='text-gray-400 text-sm'>{dealership.name}</span>}
          <button onClick={() => router.push('/settings')} className='text-gray-400 hover:text-white transition-colors'><Settings className='w-5 h-5' /></button>
          <button onClick={logout} className='text-gray-400 hover:text-white transition-colors'><LogOut className='w-5 h-5' /></button>
        </div>
      </header>

      <main className='max-w-4xl mx-auto px-6 py-8 space-y-8'>
        {/* Generate Section */}
        <div className='card'>
          <div className='flex items-center gap-3 mb-6'>
            <Video className='w-6 h-6 text-brand' />
            <h2 className='text-xl font-bold'>Generate Walkaround Video</h2>
          </div>

          {salespersons.length === 0 ? (
            <div className='text-center py-8'>
              <p className='text-gray-400 mb-4'>You need to add a salesperson before generating videos.</p>
              <button onClick={() => router.push('/settings')} className='btn-primary'>
                <Plus className='w-4 h-4 inline mr-2' />Add Salesperson
              </button>
            </div>
          ) : (
            <form onSubmit={handleGenerate} className='space-y-4'>
              <div>
                <label className='block text-sm font-medium text-gray-400 mb-1'>Vehicle Page URL</label>
                <input className='input' type='url' value={vehicleUrl} onChange={e => setVehicleUrl(e.target.value)}
                  placeholder='https://www.immaculateusedcars.com/used/Toyota/...' required />
                <p className='text-xs text-gray-500 mt-1'>Paste the full URL of the vehicle listing page</p>
              </div>
              <div>
                <label className='block text-sm font-medium text-gray-400 mb-1'>Salesperson</label>
                <select className='input' value={selectedSp} onChange={e => setSelectedSp(e.target.value)} required>
                  {salespersons.map(sp => <option key={sp.id} value={sp.id}>{sp.name}</option>)}
                </select>
              </div>
              {error && <div className='bg-red-900/50 border border-red-500 text-red-300 px-4 py-3 rounded-xl text-sm'>{error}</div>}
              <button type='submit' className='btn-primary w-full' disabled={generating}>
                {generating ? <><Loader className='w-4 h-4 inline mr-2 animate-spin' />Starting...</> : <><Video className='w-4 h-4 inline mr-2' />Generate Video</>}
              </button>
            </form>
          )}
        </div>

        {/* Active Job Banner */}
        {activeJob && (
          <div className='bg-brand/20 border border-brand/50 rounded-2xl p-4 flex items-center gap-3'>
            <Loader className='w-5 h-5 text-brand animate-spin flex-shrink-0' />
            <div>
              <p className='font-semibold text-brand'>Video generating...</p>
              <p className='text-sm text-gray-400'>This takes 3-8 minutes. The page will update automatically.</p>
            </div>
          </div>
        )}

        {/* Video History */}
        <div className='card'>
          <h2 className='text-xl font-bold mb-6'>Video History</h2>
          {jobs.length === 0 ? (
            <p className='text-gray-500 text-center py-8'>No videos generated yet. Create your first one above!</p>
          ) : (
            <div className='space-y-3'>
              {jobs.map(job => (
                <div key={job.id} className='flex items-center gap-4 p-4 bg-gray-800 rounded-xl'>
                  <div className='flex-shrink-0'>{STATUS_ICONS[job.status] || STATUS_ICONS.queued}</div>
                  <div className='flex-1 min-w-0'>
                    <p className='font-medium truncate'>{job.vehicle_name || job.vehicle_url}</p>
                    <p className='text-sm text-gray-400 capitalize'>{job.status_message || job.status}</p>
                  </div>
                  <div className='text-sm text-gray-500 flex-shrink-0'>
                    {new Date(job.created_at).toLocaleDateString()}
                  </div>
                  {job.status === 'completed' && (
                    <button onClick={() => handleDownload(job.id, job.vehicle_name)}
                      className='flex items-center gap-2 bg-green-900/50 border border-green-600 text-green-400 px-3 py-2 rounded-lg hover:bg-green-900 transition-colors text-sm font-medium flex-shrink-0'>
                      <Download className='w-4 h-4' />Download
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
