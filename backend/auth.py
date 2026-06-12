from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import os
from db import supabase

router = APIRouter()
security = HTTPBearer()
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
JWT_SECRET = os.getenv('JWT_SECRET', 'change-me-please')
JWT_ALGORITHM = 'HS256'
JWT_EXPIRE_HOURS = 24 * 7

class SignupRequest(BaseModel):
    email: str
    password: str
    dealership_name: str
    website_url: str = ''
    contact_name: str = ''

class LoginRequest(BaseModel):
    email: str
    password: str

def create_token(user_id: str, email: str, dealership_id: str) -> str:
    payload = {
        'sub': user_id, 'email': email, 'dealership_id': dealership_id,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail='Invalid or expired token')

@router.post('/signup')
async def signup(req: SignupRequest):
    existing = supabase.table('users').select('id').eq('email', req.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail='Email already registered')
    dealership = supabase.table('dealerships').insert({
        'name': req.dealership_name, 'website_url': req.website_url,
        'plan': 'free', 'videos_generated_this_month': 0
    }).execute()
    dealership_id = dealership.data[0]['id']
    hashed_pw = pwd_context.hash(req.password)
    user = supabase.table('users').insert({
        'email': req.email, 'password_hash': hashed_pw,
        'dealership_id': dealership_id, 'contact_name': req.contact_name, 'role': 'admin'
    }).execute()
    user_id = user.data[0]['id']
    token = create_token(user_id, req.email, dealership_id)
    return {'token': token, 'dealership_id': dealership_id, 'user_id': user_id}

@router.post('/login')
async def login(req: LoginRequest):
    user_result = supabase.table('users').select('*').eq('email', req.email).execute()
    if not user_result.data:
        raise HTTPException(status_code=401, detail='Invalid credentials')
    user = user_result.data[0]
    if not pwd_context.verify(req.password, user['password_hash']):
        raise HTTPException(status_code=401, detail='Invalid credentials')
    token = create_token(user['id'], user['email'], user['dealership_id'])
    return {'token': token, 'dealership_id': user['dealership_id'], 'user_id': user['id']}

@router.get('/me')
async def get_me(current_user: dict = Depends(get_current_user)):
    user = supabase.table('users').select('*, dealerships(*)').eq('id', current_user['sub']).execute()
    return user.data[0] if user.data else {}