import redis
import json

import os
r = redis.Redis(host=os.environ.get("REDIS_HOST", "localhost"), port=int(os.environ.get("REDIS_PORT", 6379)), decode_responses=True)


def cache_get(key):
    val = r.get(key)
    if val:
        return json.loads(val)
    return None


def cache_set(key, value, ttl=300):
    r.setex(key, ttl, json.dumps(value))


def clear_rag_cache():
    for key in r.keys('*'):
        if len(key) == 32 and all(c in '0123456789abcdefABCDEF' for c in key):
            r.delete(key)