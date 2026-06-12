import axios from 'axios';

const API = axios.create({ baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000' });

API.interceptors.request.use(config => {
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export const auth = {
  signup: (data: any) => API.post('/auth/signup', data).then(r => r.data),
  login: (data: any) => API.post('/auth/login', data).then(r => r.data),
  me: () => API.get('/auth/me').then(r => r.data),
};

export const video = {
  generate: (data: any) => API.post('/video/generate', data).then(r => r.data),
  status: (jobId: string) => API.get(`/video/status/${jobId}`).then(r => r.data),
  history: () => API.get('/video/history').then(r => r.data),
  downloadUrl: (jobId: string) => `${process.env.NEXT_PUBLIC_API_URL}/video/download/${jobId}`,
};

export const onboarding = {
  getSalespersons: () => API.get('/onboarding/salespersons').then(r => r.data),
  addSalesperson: (data: any) => API.post('/onboarding/salespersons', data).then(r => r.data),
  deleteSalesperson: (id: string) => API.delete(`/onboarding/salespersons/${id}`).then(r => r.data),
  getAvatars: () => API.get('/onboarding/heygen/avatars').then(r => r.data),
  getVoices: () => API.get('/onboarding/heygen/voices').then(r => r.data),
  getDealership: () => API.get('/onboarding/dealership').then(r => r.data),
};

export default API;