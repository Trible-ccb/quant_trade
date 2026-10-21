# -*- coding: utf-8 -*-
"""
外部Redis桥接进程：Redis -> 命名管道
运行环境：外部独立Python 3.8+
依赖：pip install redis pywin32
"""
import redis
import json
import time
import base64
import win32pipe
import win32file
import pywintypes

# ---------- Config ----------
REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASSWORD = '1A2B3C4D'
REDIS_KEY = 'QMT_SIGNAL'

PIPE_NAME = r'\\.\pipe\QMT_SIGNAL_PIPE_V2'
PIPE_BUFFER_SIZE = 65536  # 64KB
ERROR_PIPE_CONNECTED = 535  # Windows 错误码

def create_pipe_server():
    """创建命名管道服务端"""
    pipe = win32pipe.CreateNamedPipe(
        PIPE_NAME,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
        win32pipe.PIPE_UNLIMITED_INSTANCES,
        PIPE_BUFFER_SIZE,
        PIPE_BUFFER_SIZE,
        0,
        None
    )
    return pipe


def write_to_pipe(pipe, data_dict):
    """向命名管道写入JSON数据"""
    try:
        data_bytes = json.dumps(data_dict).encode('utf-8')
        win32file.WriteFile(pipe, data_bytes)
        return True
    except Exception as e:
        print("[PIPE] Write error: %s" % e)
        return False


def main():
    print("[OK] External Redis bridge starting...")
    print("[OK] Pipe name: %s" % PIPE_NAME)

    r = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
        db=0, decode_responses=True,
        socket_connect_timeout=3, socket_timeout=3,
        protocol=2
    )

    try:
        r.ping()
        print("[OK] Redis connection established")
    except Exception as e:
        print("[ERROR] Cannot connect to Redis: %s" % e)
        return

    pipe = create_pipe_server()
    connected = False
    try:
        while True:
            if not connected:
                print("[PIPE] Waiting for QMT strategy to connect...", flush=True)
                try:
                    win32pipe.ConnectNamedPipe(pipe, None)
                    connected = True
                    print("[PIPE] QMT strategy connected", flush=True)
                except pywintypes.error as e:
                    if e.args[0] == ERROR_PIPE_CONNECTED:
                        # 客户端在 ConnectNamedPipe 之前已经连上
                        connected = True
                        print("[PIPE] QMT strategy already connected", flush=True)
                    else:
                        print("[PIPE] Connect error: %s" % e, flush=True)
                        time.sleep(1)
                        continue

            # 从Redis读取信号
            item = r.rpop(REDIS_KEY)
            if not item:
                time.sleep(0.05)
                continue

            try:
                msg_data = json.loads(item)

                # 通过管道发送
                if write_to_pipe(pipe, msg_data):
                    print("[BRIDGE] Signal %s sent via pipe" % msg_data.get('id'))
                else:
                    # 写入失败，可能客户端已断开
                    connected = False
                    win32file.CloseHandle(pipe)
                    pipe = create_pipe_server()

            except Exception as e:
                print("[BRIDGE] Signal error: %s" % e)

    except KeyboardInterrupt:
        print("Bridge exiting...")
    finally:
        if pipe:
            win32file.CloseHandle(pipe)
        r.connection_pool.disconnect()


if __name__ == '__main__':
    main()