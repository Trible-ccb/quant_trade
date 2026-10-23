# -*- coding: utf-8 -*-
"""
外部Redis桥接进程
双向桥接：
  1. Redis -> 命名管道(QMT_SIGNAL_PIPE_V2)：把聚宽下单信号转发给 QMT 下单
  2. 命名管道(QMT_POSITION_PIPE) -> Redis：接收 QMT 定时写入的持仓快照，回写到 Redis
运行环境：外部独立 Python 3.8+
依赖：pip install redis pywin32
"""
import redis
import json
import time
import base64
import threading
import win32pipe
import win32file
import win32event
import pywintypes

# ---------- Config ----------
REDIS_HOST = '127.0.0.1'
REDIS_PORT = 6379
REDIS_PASSWORD = '1A2B3C4D'
REDIS_SIGNAL_KEY = 'QMT_SIGNAL'          # 聚宽 -> QMT 下单信号队列
REDIS_POSITION_KEY = 'QMT_POSITION'      # QMT 持仓快照（最新一份，覆盖写）

# 信号管道：bridge 作为服务端，QMT 作为客户端读取
SIGNAL_PIPE_NAME = r'\\.\pipe\QMT_SIGNAL_PIPE_V2'
# 持仓管道：bridge 作为服务端，QMT 作为客户端写入
POSITION_PIPE_NAME = r'\\.\pipe\QMT_POSITION_PIPE'

PIPE_BUFFER_SIZE = 65536  # 64KB
ERROR_PIPE_CONNECTED = 535        # Windows 错误码：管道已连接
ERROR_BROKEN_PIPE = 109           # 管道已断开
ERROR_NO_DATA = 232               # 管道无数据
CONNECT_TIMEOUT_MS = 1000         # 等待客户端连接的超时时间(ms)
READ_TIMEOUT_MS = 500             # 读管道超时时间(ms)


def create_pipe_server(pipe_name):
    """创建命名管道服务端"""
    pipe = win32pipe.CreateNamedPipe(
        pipe_name,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
        win32pipe.PIPE_UNLIMITED_INSTANCES,
        PIPE_BUFFER_SIZE,
        PIPE_BUFFER_SIZE,
        0,
        None
    )
    return pipe


def wait_for_client(pipe, timeout_ms=CONNECT_TIMEOUT_MS):
    """
    等待客户端连接（非阻塞，支持超时）。
    返回 True 表示已连接，False 表示超时。
    """
    overlapped = pywintypes.OVERLAPPED()
    overlapped.hEvent = win32event.CreateEvent(None, 0, 0, None)
    try:
        try:
            win32pipe.ConnectNamedPipe(pipe, overlapped)
        except pywintypes.error as e:
            if e.args[0] == ERROR_PIPE_CONNECTED:
                # 客户端已经提前连上
                return True
            if e.args[0] != 997:  # ERROR_IO_PENDING
                print("[PIPE] Connect error: %s" % e, flush=True)
                return False

        rc = win32event.WaitForSingleObject(overlapped.hEvent, timeout_ms)
        if rc == win32event.WAIT_OBJECT_0:
            return True
        # 超时，取消挂起的连接
        win32file.CancelIo(pipe)
        return False
    finally:
        win32event.CloseHandle(overlapped.hEvent)


def write_to_pipe(pipe, data_dict):
    """向命名管道写入 JSON 数据"""
    try:
        data_bytes = json.dumps(data_dict).encode('utf-8')
        win32file.WriteFile(pipe, data_bytes)
        return True
    except pywintypes.error as e:
        if e.args[0] == ERROR_BROKEN_PIPE or e.args[0] == ERROR_NO_DATA:
            return False
        print("[PIPE] Write error: %s" % e)
        return False
    except Exception as e:
        print("[PIPE] Write error: %s" % e)
        return False


def read_from_pipe(pipe, timeout_ms=READ_TIMEOUT_MS):
    """
    从命名管道读取一条消息（阻塞读取，带超时）。
    返回 (status, data_str)：
      status = 'data'  读到一条数据
      status = 'timeout' 超时无数据
      status = 'broken' 管道已断开
    """
    overlapped = pywintypes.OVERLAPPED()
    overlapped.hEvent = win32event.CreateEvent(None, 0, 0, None)
    buf = win32file.AllocateReadBuffer(PIPE_BUFFER_SIZE)
    try:
        try:
            hr, data = win32file.ReadFile(pipe, buf, overlapped)
        except pywintypes.error as e:
            if e.args[0] == ERROR_BROKEN_PIPE:
                return ('broken', None)
            if e.args[0] != 997:  # 非 ERROR_IO_PENDING
                print("[PIPE] Read error: %s" % e, flush=True)
                return ('broken', None)
            hr = 0
            data = None

        if hr != 0:
            # 同步读到了数据
            return ('data', data.decode('utf-8', errors='ignore'))

        rc = win32event.WaitForSingleObject(overlapped.hEvent, timeout_ms)
        if rc != win32event.WAIT_OBJECT_0:
            # 超时，取消读取
            win32file.CancelIo(pipe)
            return ('timeout', None)

        nread = win32file.GetOverlappedResult(pipe, overlapped, False)
        return ('data', buf[:nread].decode('utf-8', errors='ignore'))
    except pywintypes.error as e:
        if e.args[0] == ERROR_BROKEN_PIPE or e.args[0] == ERROR_NO_DATA:
            return ('broken', None)
        print("[PIPE] Read error: %s" % e, flush=True)
        return ('broken', None)
    finally:
        win32event.CloseHandle(overlapped.hEvent)


# ============================================================
# 线程 1：信号转发 Redis -> QMT 管道
# ============================================================
def signal_forward_loop(r):
    """从 Redis 取出下单信号，转发给 QMT 命名管道。支持 QMT 反复断开/重连。"""
    print("[SIGNAL] Signal forward loop started", flush=True)

    pipe = None
    connected = False

    while True:
        # 1. 确保有可用的管道连接
        if not connected:
            if pipe is not None:
                try:
                    win32file.CloseHandle(pipe)
                except Exception:
                    pass
                pipe = None

            pipe = create_pipe_server(SIGNAL_PIPE_NAME)
            print("[PIPE] Waiting for QMT strategy to connect...", flush=True)
            if wait_for_client(pipe):
                connected = True
                print("[PIPE] QMT strategy connected", flush=True)
            else:
                # 超时未连上，短暂让出 CPU 后重试
                time.sleep(0.2)
                continue

        # 2. 从 Redis 读取一条信号
        item = r.rpop(REDIS_SIGNAL_KEY)
        if not item:
            # 无信号，短暂等待（不阻塞管道检查）
            time.sleep(0.05)
            continue

        try:
            msg_data = json.loads(item)
        except Exception as e:
            print("[BRIDGE] Invalid signal JSON: %s" % e, flush=True)
            continue

        # 3. 写入管道
        if write_to_pipe(pipe, msg_data):
            print("[BRIDGE] Signal %s sent via pipe" % msg_data.get('id'), flush=True)
        else:
            # 写入失败，说明客户端断开，重置连接状态，等待重连
            print("[PIPE] Write failed, QMT disconnected. Will reconnect...", flush=True)
            connected = False
            # 信号写回队列，避免丢失（恢复到队首，稍后重发）
            try:
                r.lpush(REDIS_SIGNAL_KEY, item)
            except Exception:
                pass


# ============================================================
# 线程 2：持仓快照 QMT 管道 -> Redis
# ============================================================
def position_ingest_loop(r):
    """从 QMT 命名管道读取持仓快照，写入 Redis。支持 QMT 反复断开/重连。"""
    print("[POSITION] Position ingest loop started", flush=True)

    pipe = None
    connected = False

    while True:
        if not connected:
            if pipe is not None:
                try:
                    win32file.CloseHandle(pipe)
                except Exception:
                    pass
                pipe = None

            pipe = create_pipe_server(POSITION_PIPE_NAME)
            print("[POSITION] Waiting for QMT position writer to connect...", flush=True)
            if wait_for_client(pipe):
                connected = True
                print("[POSITION] QMT position writer connected", flush=True)
            else:
                time.sleep(0.2)
                continue

        status, data_str = read_from_pipe(pipe)
        if status == 'broken':
            print("[POSITION] Pipe broken, will reconnect...", flush=True)
            connected = False
            continue
        if status == 'timeout':
            continue
        if data_str is None:
            continue

        # 解析持仓快照
        try:
            snapshot = json.loads(data_str)
        except Exception as e:
            print("[POSITION] Invalid snapshot JSON: %s" % e, flush=True)
            continue

        # 写入 Redis（覆盖写，只保留最新一份快照）
        try:
            r.set(REDIS_POSITION_KEY, json.dumps(snapshot, ensure_ascii=False))
            print("[POSITION] Snapshot saved, ts=%s" % snapshot.get('ts', 'N/A'), flush=True)
        except Exception as e:
            print("[POSITION] Redis write error: %s" % e, flush=True)


def main():
    print("[OK] External Redis bridge starting...")
    print("[OK] Signal pipe  : %s" % SIGNAL_PIPE_NAME)
    print("[OK] Position pipe: %s" % POSITION_PIPE_NAME)

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

    # 启动两个工作线程
    t_signal = threading.Thread(target=signal_forward_loop, args=(r,), daemon=True, name='signal-forward')
    t_position = threading.Thread(target=position_ingest_loop, args=(r,), daemon=True, name='position-ingest')
    t_signal.start()
    t_position.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Bridge exiting...")
    finally:
        r.connection_pool.disconnect()


if __name__ == '__main__':
    main()
