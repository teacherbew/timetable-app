from fastapi import Request, HTTPException
from app.redis_client import redis_client

def rate_limit(request: Request):
    client_ip = request.client.host
    key = f"rate_limit:{client_ip}"
    
    # นับจำนวน Request
    requests = redis_client.incr(key)
    
    if requests == 1:
        redis_client.expire(key, 60)  # ตั้งเวลาเคลียร์ทุก 60 วินาที
        
    if requests > 10:  # เกิน 10 ครั้ง/นาที
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute.")