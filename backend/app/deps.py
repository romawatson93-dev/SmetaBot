from fastapi import Depends
from .db import get_db

async def get_session(db=Depends(get_db)):
    return db
