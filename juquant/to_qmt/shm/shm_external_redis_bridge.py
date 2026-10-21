# -*- coding: utf-8 -*-
import redis
import json
import time
import base64
from shm_queue import SharedMemoryQueue

# ---------- Config ----------
REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASSWORD = '1A2B3C4D'
REDIS_KEY = 'QMT_SIGNAL'

def main():
    # Create shared memory (must start before QMT strategy)
    shm_queue = SharedMemoryQueue(create=True)
    print("[OK] External Redis bridge started, shared memory '%s' created" % shm_queue.shm.name)
    
    r = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
        db=0, decode_responses=True, socket_connect_timeout=3, socket_timeout=3,
        protocol=2
    )
    
    try:
        while True:
            item = r.rpop(REDIS_KEY)
            if not item:
                time.sleep(0.1)  # Avoid busy polling
                continue
                
            try:
                decoded_item = base64.b64decode(item).decode('utf-8')
                msg_data = json.loads(decoded_item)
                
                # Write to shared memory
                if shm_queue.push(msg_data):
                    print("[BRIDGE] Signal %s written to shared memory" % msg_data.get('id'))
                    
            except Exception as e:
                print("[BRIDGE] Error processing signal: %s" % e)
                
    except KeyboardInterrupt:
        print("External bridge process exiting")
    finally:
        r.connection_pool.disconnect()
        shm_queue.close()
        shm_queue.unlink()  # Clean up shared memory on exit

if __name__ == '__main__':
    main()