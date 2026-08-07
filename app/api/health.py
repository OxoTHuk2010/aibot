
from fastapi import APIRouter

router = APIRouter(prefix='api/health', tags=['Heath'])

@router.get('/')
def health():
    pass