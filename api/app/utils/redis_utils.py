from functools import cache
from redis import Redis
from config import (
    REDIS_HOST,
    REDIS_PORT,
    REDIS_DB,
    REDIS_JOB_LIST,
    SUBMISSION_RATE_LIMIT,
    SUBMISSION_RATE_WINDOW_SECONDS,
)

redis_client = Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

@cache
def get_redis_client():
    return Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        decode_responses=True,
    )

def enqueue_job(submission_id: int):
    get_redis_client().lpush(REDIS_JOB_LIST, submission_id)


def check_submission_rate_limit(user_id: int) -> int:
    retry_after = get_redis_client().eval(
        """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then
            redis.call('EXPIRE', KEYS[1], ARGV[2])
        end
        if count > tonumber(ARGV[1]) then
            return redis.call('TTL', KEYS[1])
        end
        return 0
        """,
        1,
        f"submissions:rate_limit:user:{user_id}",
        SUBMISSION_RATE_LIMIT,
        SUBMISSION_RATE_WINDOW_SECONDS,
    )
    return max(int(retry_after), 1) if retry_after else 0
