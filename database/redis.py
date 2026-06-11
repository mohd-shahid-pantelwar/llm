import redis
import json

r = redis.Redis(host="10.0.10.131", port=6379, decode_responses=True)


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