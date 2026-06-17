from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from auth import get_current_user
from db import supabase
import os, uuid, requests

router = APIRouter()

@router.get('/salespersons')
async def list_salespersons(current_user: dict = Depends(get_current_user)):
    result = supabase.table('salespersons').select('*').eq('dealership_id', current_user['dealership_id']).execute()
    return result.data

class AddSalespersonRequest(BaseModel):
    name: str
    heygen_avatar_id: str
    heygen_voice_id: str
    lot_background_url: str = ''

@router.post('/salespersons')
async def add_salesperson(req: AddSalespersonRequest, current_user: dict = Depends(get_current_user)):
    result = supabase.table('salespersons').insert({
        'dealership_id': current_user['dealership_id'],
        'name': req.name,
        'heygen_avatar_id': req.heygen_avatar_id,
        'heygen_voice_id': req.heygen_voice_id,
        'lot_background_url': req.lot_background_url
    }).execute()
    return result.data[0]

class UpdateSalespersonRequest(BaseModel):
    source_video_url: Optional[str] = None
    lot_background_url: Optional[str] = None
    heygen_voice_id: Optional[str] = None

@router.patch('/salespersons/{sp_id}')
async def update_salesperson(sp_id: str, req: UpdateSalespersonRequest, current_user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        return {'ok': True}
    # Verify ownership
    existing = supabase.table('salespersons').select('id').eq('id', sp_id).eq('dealership_id', current_user['dealership_id']).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail='Salesperson not found')
    result = supabase.table('salespersons').update(updates).eq('id', sp_id).execute()
    return result.data[0] if result.data else {'ok': True}

@router.delete('/salespersons/{sp_id}')
async def remove_salesperson(sp_id: str, current_user: dict = Depends(get_current_user)):
    supabase.table('salespersons').delete().eq('id', sp_id).eq('dealership_id', current_user['dealership_id']).execute()
    return {'ok': True}

@router.get('/heygen/avatars')
async def get_heygen_avatars(current_user: dict = Depends(get_current_user)):
    from heygen_client import list_avatars
    return list_avatars()

@router.get('/heygen/voices')
async def get_heygen_voices(current_user: dict = Depends(get_current_user)):
    from heygen_client import list_voices
    return list_voices()

@router.get('/dealership')
async def get_dealership(current_user: dict = Depends(get_current_user)):
    result = supabase.table('dealerships').select('*').eq('id', current_user['dealership_id']).execute()
    return result.data[0] if result.data else {}

class UpdateDealershipRequest(BaseModel):
    name: str = None
    website_url: str = None
    lot_background_url: str = None

@router.patch('/dealership')
async def update_dealership(req: UpdateDealershipRequest, current_user: dict = Depends(get_current_user)):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates: return {'ok': True}
    result = supabase.table('dealerships').update(updates).eq('id', current_user['dealership_id']).execute()
    return result.data[0]
