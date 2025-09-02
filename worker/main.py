import os, time, sys
import redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

def main():
    print(f"[worker] starting, REDIS_URL={REDIS_URL}", flush=True)
    r = redis.Redis.from_url(REDIS_URL)
    while True:
        try:
            r.ping()
            print("[worker] ping ok", flush=True)
        except Exception as e:
            print(f"[worker] ping failed: {e}", file=sys.stderr, flush=True)
        time.sleep(10)

if __name__ == "__main__":
    main()
