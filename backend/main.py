from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from auth import router as auth_router
from video import router as video_router
from onboarding import router as onboarding_router

app = FastAPI(title='AutoWalkaround API', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth_router, prefix='/auth', tags=['auth'])
app.include_router(video_router, prefix='/video', tags=['video'])
app.include_router(onboarding_router, prefix='/onboarding', tags=['onboarding'])

@app.get('/health')
def health(): return {'status': 'ok'}

if __name__ == '__main__':
    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)