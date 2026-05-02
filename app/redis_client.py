import os
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")

redis_client = redis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)

LUA_SWEEP = """
local members = redis.call('SMEMBERS', KEYS[1])
if #members > 0 then
    redis.call('DEL', KEYS[1])
end
return members
"""
sweep_script = redis_client.register_script(LUA_SWEEP)

def mark_segments_dirty(segment_ids: list[int]):
    if not segment_ids: return
    redis_client.sadd("dirty_segments", *segment_ids)

def sweep_dirty_segments() -> list[int]:
    result = sweep_script(keys=["dirty_segments"])
    return [int(x) for x in result] if result else []