# coding:gbk
"""
QMT内置策略：用ctypes直接调用Windows API操作命名管道
无需安装任何第三方库
"""
import ctypes
from ctypes import wintypes
import json
import time
import datetime

ACCOUNT_ID = '***'

# ============================================================
# Win32 API Setup
# ============================================================
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
PIPE_READMODE_MESSAGE = 0x00000002

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE
]
kernel32.CreateFileW.restype = wintypes.HANDLE

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

kernel32.ReadFile.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
]
kernel32.ReadFile.restype = wintypes.BOOL

kernel32.PeekNamedPipe.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD)
]
kernel32.PeekNamedPipe.restype = wintypes.BOOL

kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
kernel32.WaitNamedPipeW.restype = wintypes.BOOL

# --- 新增：SetNamedPipeHandleState ---
kernel32.SetNamedPipeHandleState.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD)
]
kernel32.SetNamedPipeHandleState.restype = wintypes.BOOL

# ============================================================
# Config
# ============================================================
PIPE_NAME = u"\\\\.\\pipe\\QMT_SIGNAL_PIPE_V2"
PIPE_BUFFER_SIZE = 65536
SIGNAL_MAX_DELAY = 30
PROCESSED_IDS = set()
_pipe_handle = None


# ============================================================
# Pipe Helper Functions
# ============================================================
def _is_invalid_handle(h):
    if h is None or h == 0 or h == -1 or h == 0xFFFFFFFFFFFFFFFF:
        return True
    return False


def _connect_pipe():
    """Connect to the named pipe as a client, in message-read mode."""
    global _pipe_handle

    if not kernel32.WaitNamedPipeW(PIPE_NAME, 200):
        return False

    handle = kernel32.CreateFileW(
        PIPE_NAME,
        GENERIC_READ | GENERIC_WRITE,
        0, None, OPEN_EXISTING, 0, None
    )

    if _is_invalid_handle(handle):
        return False

    # Set this side to message-read mode, matching the server's PIPE_TYPE_MESSAGE
    mode = wintypes.DWORD(PIPE_READMODE_MESSAGE)
    ok = kernel32.SetNamedPipeHandleState(
        handle, ctypes.byref(mode), None, None
    )
    if not ok:
        err = ctypes.get_last_error()
        print("[PIPE] SetNamedPipeHandleState failed, err=%d" % err)
        kernel32.CloseHandle(handle)
        return False

    _pipe_handle = handle
    return True


def _read_message_nonblocking(handle):
    """Return (status, data). status: True=pipe OK, False=pipe broken."""
    avail = wintypes.DWORD(0)
    ok = kernel32.PeekNamedPipe(
        handle, None, 0, None,
        ctypes.byref(avail), None
    )
    if not ok:
        return (False, None)   # pipe broken
    if avail.value == 0:
        return (True, None)    # no data

    buf = ctypes.create_string_buffer(PIPE_BUFFER_SIZE)
    bytes_read = wintypes.DWORD(0)
    ok = kernel32.ReadFile(
        handle, buf, PIPE_BUFFER_SIZE,
        ctypes.byref(bytes_read), None
    )
    if not ok or bytes_read.value == 0:
        return (False, None)

    return (True, buf.raw[:bytes_read.value].decode('utf-8'))


def _close_pipe():
    global _pipe_handle
    if _pipe_handle is not None:
        try:
            kernel32.CloseHandle(_pipe_handle)
        except:
            pass
        _pipe_handle = None


# ============================================================
# QMT Strategy Entry
# ============================================================
def init(ContextInfo):
    ContextInfo.account_id = ACCOUNT_ID
    ContextInfo.set_account(ACCOUNT_ID)
    current_time = datetime.datetime.now()
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
    ContextInfo.run_time('poll_pipe_signals', '500nMilliSecond', formatted_time)
    print("[OK] QMT pipe reader started (ctypes mode), account: %s" % ACCOUNT_ID)


def order_callback(ContextInfo, orderInfo):
    print('orderInfo %s' % orderInfo)


def is_kcb_stock(stock_code):
    return stock_code.startswith('688')

def poll_pipe_signals(ContextInfo):
    global _pipe_handle

    try:
        if _pipe_handle is None:
            if not _connect_pipe():
                return
            print("[PIPE] Connected to bridge")

        status, msg_str = _read_message_nonblocking(_pipe_handle)
        if not status:
            print("[PIPE] Pipe broken, will reconnect...")
            _close_pipe()
            return
        if msg_str is None:
            return

        try:
            msg_data = json.loads(msg_str)
        except ValueError as e:
            print("[PARSE] JSON error: %s" % e)
            return

        process_signal(msg_data, ContextInfo)

    except Exception as e:
        import traceback
        print("[POLL] Exception: %s\n%s" % (e, traceback.format_exc()))
        _close_pipe()


def process_signal(msg_data, ContextInfo):
    signal_id = msg_data.get('id')
    gen_time = float(msg_data.get('gen_time', 0))
    action = msg_data.get('action')
    strategy = msg_data.get('strategy')
    stock_code = msg_data.get('stock')
    amount = int(msg_data.get('amount', 0))
    signal_price = float(msg_data.get('price', 0))

    current_time = datetime.datetime.now()
    now = current_time.timestamp()
    delay = now - gen_time if gen_time > 0 else -1
    formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S")

    print("%s[Signal] id=%s delay=%.3fs action=%s stock=%s amount=%d, price=%.3f" % (
        formatted_time, signal_id, delay, action, stock_code, amount, signal_price))

    if signal_id is None or signal_id in PROCESSED_IDS:
        print("[Idempotent] Skip id=%s" % signal_id)
        return

    if delay > SIGNAL_MAX_DELAY:
        print("[Expired] delay=%.3fs" % delay)
        return

    PROCESSED_IDS.add(signal_id)

    if amount == 0:
        print("[Skip] amount=0")
        return

    is_kcb = is_kcb_stock(stock_code)

    if action == 'buy':
        op_type = 23
        order_price = signal_price * (1 + 0.005) if signal_price > 0 else 0
    elif action == 'sell':
        op_type = 24
        order_price = signal_price * (1 - 0.005) if signal_price > 0 else 0
    else:
        print("[Unknown] action=%s" % action)
        return

    try:
        print("[Order] %s %s %d @ %.3f id=%s" % (
                    action, stock_code, amount, order_price, signal_id))
        passorder(
            op_type, 1101, ContextInfo.account_id, stock_code,
            11, order_price, amount, "QMT_%s" % strategy,
            1, "%s" % signal_id, ContextInfo
        )
        
    except Exception as e:
        print("[Order Failed] %s id=%s" % (e, signal_id))