#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Python自动交易器（无价格输入版）
================================

功能概述：
通过 Python 代码生成交易信号，自动在同花顺客户端执行下单操作。
本版本不手动输入价格，由同花顺界面自动填充价格（买入用卖二，卖出用买二）。

架构设计：
┌──────────────────┐          ┌──────────────────────┐          ┌──────────────────┐
│  量化策略系统     │          │  PythonAutoTrade     │          │  同花顺客户端     │
│  (产生交易信号)   │ ───────> │  (执行下单)           │ ───────> │  (实际成交)      │
└──────────────────┘          └──────────┬───────────┘          └──────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              ┌──────────┐        ┌───────────┐        ┌───────────┐
              │ 配置模块  │        │ 日志系统   │        │ 执行器模块 │
              │ 加载/保存 │        │ 输出/队列  │        │ 键盘/HTTP  │
              └──────────┘        └───────────┘        └───────────┘

核心功能：
1. 键盘模拟模式（默认）：通过 SendInput 模拟真实键盘操作同花顺窗口
2. HTTP推送模式：通过跟单控制面板的 PubSvr /publish 接口推送信号
3. 自动检测同花顺窗口标题
4. 支持功能键下单（F1买入/F2卖出）和快速交易两种模式
5. 不手动输入价格，由同花顺界面自动填充（买入=卖二价，卖出=买二价）

与原版区别：
- 移除了 _clear_and_type_price 方法及相关价格输入逻辑
- 下单时不输入价格，Tab跳过价格框，使用同花顺界面自动填充的价格
- buy/sell/trade 方法的 price 参数保留但不再使用

使用示例：
    from PythonAutoTrade_noprice import AutoTrader
    
    trader = AutoTrader()
    trader.trade("000001", "buy", 1000)    # 买入平安银行1000股（价格由界面自动填充）
    trader.trade("600036", "sell", 500)    # 卖出招商银行500股（价格由界面自动填充）

参数配置（自动交易配置.json）：
    - ths_exe_path: 同花顺下单程序路径（自动检测）
    - order_mode: 下单模式（function_key / quick）
    - key_delay: 按键间隔（秒）
    - window_title_keyword: 同花顺窗口标题关键词（留空自动匹配）
    - follow_ratio: 跟单比例（默认1.0）
    - min_amount: 最小下单量（默认100股）
    - http_push_url: HTTP推送地址（启用HTTP模式时使用）
    - http_token: HTTP推送认证令牌（可选）
"""

import os
import sys
import json
import time
import threading
import queue as qqueue
import urllib.request
import urllib.error
from datetime import datetime

try:
    import ctypes
    from ctypes import wintypes
except ImportError:
    print("需要 ctypes 模块（Windows系统）")
    sys.exit(1)

# 设置DPI感知，解决Windows高DPI缩放导致截图模糊问题
try:
    ctypes.windll.user32.SetProcessDPIAware()
    print("✅ DPI感知已设置")
except Exception as e:
    print("⚠️ DPI感知设置失败: %s" % e)



# ===========================================================================
# 路径与配置模块
# ===========================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "自动交易配置.json")

DEFAULT_CONFIG = {
    "ths_exe_path": r"D:\同花顺软件\同花顺\xiadan.exe",
    "order_mode": "function_key",      # 下单模式：function_key（F1/F2）或 quick（快速交易）
    "key_delay": 0.5,                  # 按键间隔（秒），根据电脑性能调整
    "window_title_keyword": "",        # 窗口标题关键词（留空自动匹配）
    "follow_ratio": 1.0,               # 跟单比例，1.0表示全额跟单
    "min_amount": 100,                 # 最小下单量（股）
    "http_push_url": "",               # HTTP推送地址
    "http_token": "",                  # HTTP认证令牌
}


def _autodetect_ths_path():    
    return r"D:\同花顺软件\同花顺\xiadan.exe"

def load_config():
    """加载配置文件
    
    加载顺序：
    1. 使用默认配置
    2. 自动检测同花顺路径覆盖默认配置
    3. 如果存在配置文件，用文件内容覆盖
    
    返回：
        dict，完整配置字典
    """
    cfg = dict(DEFAULT_CONFIG)
    cfg["ths_exe_path"] = _autodetect_ths_path()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            cfg.update(saved)
        except Exception:
            pass
    return cfg


def save_config(cfg):
    """保存配置到文件
    
    参数：
        cfg: dict，配置字典
    """
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("保存配置失败: %s" % e)


# ===========================================================================
# 日志系统
# ===========================================================================
LOG_QUEUE = qqueue.Queue()  # 日志队列，用于外部程序读取日志


def log(msg, level="INFO"):
    """日志输出函数
    
    参数：
        msg: str，日志消息
        level: str，日志级别（INFO/WARN/ERROR/OK）
    
    输出：
        1. 控制台打印
        2. 存入日志队列供其他模块读取
    """
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "[INFO]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[OK]"}.get(level, "[INFO]")
    line = "%s %s %s" % (ts, prefix, msg)
    print(line)
    LOG_QUEUE.put((level, line))


# ===========================================================================
# 键盘下单执行器（核心模块）
# ===========================================================================

# Windows API 常量定义
_KEYEVENTF_EXTENDEDKEY = 0x0001  # 扩展键标志
_WM_KEYDOWN = 0x0100              # 键盘按下消息
_WM_KEYUP = 0x0101                # 键盘释放消息
_WM_CHAR = 0x0102                 # 字符消息

# 常用虚拟键码（Virtual Key Code）
_VK_RETURN = 0x0D  # 回车键
_VK_TAB = 0x09     # Tab键
_VK_F1 = 0x70      # F1键（买入）
_VK_F2 = 0x71      # F2键（卖出）
_VK_F4 = 0x73      # F4键（查询）
_VK_BACK = 0x08    # 退格键
_VK_ESCAPE = 0x1B  # ESC键
_VK_0 = 0x30       # 数字0

# SendInput 相关常量
INPUT_KEYBOARD = 1              # 输入类型：键盘
KEYEVENTF_KEYUP = 0x0002        # 按键释放标志
KEYEVENTF_SCANCODE = 0x0008     # 使用扫描码标志


class KEYBDINPUT(ctypes.Structure):
    """键盘输入结构体（对应 Windows API 的 KEYBDINPUT）
    
    用于 SendInput 函数发送键盘事件
    """
    _fields_ = [
        ("wVk", ctypes.c_ushort),        # 虚拟键码（使用扫描码时设为0）
        ("wScan", ctypes.c_ushort),      # 扫描码（物理键盘位置编码）
        ("dwFlags", ctypes.c_ulong),     # 标志位（KEYEVENTF_KEYUP/KEYEVENTF_SCANCODE）
        ("time", ctypes.c_ulong),        # 时间戳（0表示由系统填充）
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),  # 额外信息（None）
    ]


class MOUSEINPUT(ctypes.Structure):
    """鼠标输入结构体（对应 Windows API 的 MOUSEINPUT）"""
    _fields_ = [
        ("dx", ctypes.c_long),           # X坐标
        ("dy", ctypes.c_long),           # Y坐标
        ("mouseData", ctypes.c_ulong),   # 滚轮数据
        ("dwFlags", ctypes.c_ulong),     # 鼠标事件标志
        ("time", ctypes.c_ulong),        # 时间戳
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),  # 额外信息
    ]


class HARDWAREINPUT(ctypes.Structure):
    """硬件输入结构体（对应 Windows API 的 HARDWAREINPUT）"""
    _fields_ = [
        ("uMsg", ctypes.c_ulong),        # 硬件消息
        ("wParamL", ctypes.c_short),     # 参数低字节
        ("wParamH", ctypes.c_ushort),    # 参数高字节
    ]


class INPUT_UNION(ctypes.Union):
    """INPUT结构体的联合部分
    
    支持键盘、鼠标、硬件三种输入类型
    """
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    """Windows API INPUT结构体
    
    SendInput 函数的核心参数，封装输入事件
    """
    _fields_ = [
        ("type", ctypes.c_ulong),        # 输入类型（INPUT_KEYBOARD=1）
        ("union", INPUT_UNION),          # 输入数据联合体
    ]


class KeyOrderExecutor:
    """键盘模拟下单执行器（无价格输入版）
    
    通过 Windows API 模拟键盘操作，自动在同花顺客户端下单
    不手动输入价格，由同花顺界面自动填充（买入=卖二价，卖出=买二价）
    
    两种下单模式：
    1. function_key：按 F1（买入）或 F2（卖出）进入对应界面，输入代码、数量
    2. quick：快速交易模式，直接输入代码后回车下单
    
    使用线程锁保证同一时间只有一个下单操作
    """
    
    def __init__(self, config):
        """初始化执行器
        
        参数：
            config: dict，配置字典
        """
        self.config = config
        self.ths_hwnd = None        # 同花顺窗口句柄
        self.order_count = 0        # 累计下单次数
        self._lock = threading.Lock()  # 线程锁，防止并发下单
        self._user32 = ctypes.windll.user32  # User32 库引用
    
    def find_ths_windows(self):
        """查找同花顺窗口
        
        遍历所有可见窗口，根据标题关键词匹配同花顺下单窗口
        
        过滤规则：
        - 排除浏览器窗口（Edge/Chrome/Chromium）
        - 排除命令行窗口（命令提示符/PowerShell/explorer）
        - 排除聚宽相关窗口
        
        匹配优先级：
        - 高优先级：网上股票交易、交易系统、委托下单、下单系统
        - 低优先级：网上交易、股票交易、委托交易、xiadan、ths_trade、TdxW、同花顺
        
        返回：
            list，[(hwnd, title), ...]，按优先级排序的窗口列表
        """
        result = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, lparam):
            try:
                # 跳过不可见窗口
                if not self._user32.IsWindowVisible(hwnd):
                    return True
                
                # 获取窗口标题长度
                length = self._user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True
                
                # 获取窗口标题
                buf = ctypes.create_unicode_buffer(length + 1)
                self._user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if not title:
                    return True
                
                # 排除非交易窗口
                if "聚宽" in title or "网页跟单" in title or "Playwright" in title:
                    return True
                if "Edge" in title or "Chrome" in title or "Chromium" in title:
                    return True
                if "命令提示符" in title or "PowerShell" in title or "explorer" in title.lower():
                    return True
                
                # 用户自定义关键词匹配
                user_kw = self.config.get("window_title_keyword", "").strip()
                if user_kw:
                    if user_kw in title:
                        result.append((hwnd, title, 0))
                    return True
                
                # 内置关键词匹配
                builtin_keywords = [
                    "网上股票交易", "交易系统", "委托下单",
                    "下单系统", "网上交易", "股票交易", "委托交易",
                    "xiadan", "ths_trade", "TdxW", "同花顺",
                ]
                matched_kw = None
                for kw in builtin_keywords:
                    if kw in title:
                        matched_kw = kw
                        break
                
                if matched_kw:
                    # 高优先级关键词优先级为0，其他为1
                    priority = 0 if matched_kw in ("网上股票交易", "交易系统", "委托下单", "下单系统") else 1
                    result.append((hwnd, title, priority))
            except Exception:
                pass
            return True

        self._user32.EnumWindows(_cb, 0)
        result.sort(key=lambda x: x[2])  # 按优先级排序
        return [(hwnd, title) for hwnd, title, _ in result]
    
    def _activate(self, hwnd, max_retries=3):
        """激活同花顺窗口到前台

        修复要点：
        1. 显式声明 Win32 API 的 argtypes/restype，避免 64 位 Python 下
           HWND 被 c_int 截断导致 GetForegroundWindow/SetForegroundWindow 失败。
        2. 调整顺序：AttachThreadInput（最可靠的前台锁绕过手段）在前，
           SetForegroundWindow 在后；ALT 键技巧紧贴 SetForegroundWindow 之前
           作辅助。
        3. 删除 SetWindowPos TOPMOST/NOTOPMOST 横跳：原代码用的
           0x0001|0x0002|0x0040 = SWP_NOSIZE|SWP_NOMOVE|SWP_SHOWWINDOW，
           缺少 SWP_NOACTIVATE(0x0010)，会主动激活窗口与 SetForegroundWindow
           竞争，反而造成失焦。
        4. AttachThreadInput 方向修正为 self->fg / self->target（原代码
           fg->self 方向反了，无法把前台权限授予本线程）。
        5. 处理 fg_hwnd==0（无前台）的情况，避免 AttachThreadInput 传入 0。
        6. 成功判定改为短轮询，给目标窗口异步处理 WM_ACTIVATE 的时间。
        7. 失败时提示检查 UAC 完整性级别差异。

        参数：
            hwnd: int，窗口句柄
            max_retries: int，最大重试次数

        返回：
            bool，是否成功激活到前台（失败返回 False，不会继续执行）
        """
        try:
            u32 = self._user32
            k32 = ctypes.windll.kernel32

            # ---- 显式声明 argtypes/restype（修复 64 位下 HWND 被截断的核心问题）----
            HWND, BOOL, DWORD = wintypes.HWND, wintypes.BOOL, wintypes.DWORD
            u32.IsWindow.argtypes = [HWND];                u32.IsWindow.restype = BOOL
            u32.IsIconic.argtypes = [HWND];                u32.IsIconic.restype = BOOL
            u32.IsWindowVisible.argtypes = [HWND];         u32.IsWindowVisible.restype = BOOL
            u32.ShowWindow.argtypes = [HWND, ctypes.c_int]; u32.ShowWindow.restype = BOOL
            u32.GetForegroundWindow.argtypes = [];         u32.GetForegroundWindow.restype = HWND  # 默认 c_int 会截断
            u32.GetWindowThreadProcessId.argtypes = [HWND, wintypes.LPDWORD]
            u32.GetWindowThreadProcessId.restype = DWORD
            u32.SetForegroundWindow.argtypes = [HWND];     u32.SetForegroundWindow.restype = BOOL
            u32.BringWindowToTop.argtypes = [HWND];       u32.BringWindowToTop.restype = BOOL
            u32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
            u32.AttachThreadInput.restype = BOOL
            k32.GetCurrentThreadId.argtypes = [];          k32.GetCurrentThreadId.restype = DWORD

            if not u32.IsWindow(hwnd):
                log("窗口句柄无效，无法激活 (HWND=%s)" % hwnd, "ERROR")
                return False

            SW_SHOWNORMAL = 1   # 恢复最小化/显示隐藏窗口
            VK_MENU = 0x12      # ALT

            def _is_foreground():
                return u32.GetForegroundWindow() == hwnd

            def _poll_foreground(times=6, interval=0.05):
                for _ in range(times):
                    if _is_foreground():
                        return True
                    time.sleep(interval)
                return False

            # 第 0 步：若最小化或隐藏，先恢复/显示
            if u32.IsIconic(hwnd) or not u32.IsWindowVisible(hwnd):
                u32.ShowWindow(hwnd, SW_SHOWNORMAL)
                time.sleep(0.05)

            # 快速路径：已是前台
            if _is_foreground():
                return True

            self_thread = k32.GetCurrentThreadId()
            target_thread = u32.GetWindowThreadProcessId(hwnd, None)

            for attempt in range(max_retries):
                # 每轮重取前台（可能在循环中变化）
                fg_hwnd = u32.GetForegroundWindow()
                if fg_hwnd == hwnd:
                    return True
                fg_thread = u32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

                # ---- AttachThreadInput：前台锁绕过的主手段 ----
                # 方向 self->fg：让本线程共享前台线程的输入状态，从而获得
                # 调用 SetForegroundWindow 的权限（原代码 fg->self 方向反了）。
                attached_fg = False
                if fg_thread and fg_thread != self_thread:
                    attached_fg = bool(u32.AttachThreadInput(self_thread, fg_thread, True))
                # 必要时再附加到目标窗口线程，使输入流向目标
                attached_tgt = False
                if target_thread and target_thread != self_thread \
                        and target_thread != fg_thread:
                    attached_tgt = bool(u32.AttachThreadInput(self_thread, target_thread, True))

                try:
                    # ALT 键技巧：模拟一次用户输入以释放前台锁定（辅助手段，
                    # Win10/11 下可靠性不如 AttachThreadInput）
                    self._send_input_key(VK_MENU, down=True)
                    self._send_input_key(VK_MENU, down=False)
                    time.sleep(0.02)

                    u32.BringWindowToTop(hwnd)
                    u32.SetForegroundWindow(hwnd)

                    # 短轮询确认（目标窗口异步处理 WM_ACTIVATE）
                    if _poll_foreground(times=6, interval=0.05):
                        return True
                finally:
                    # 务必解除附加，避免影响其他线程输入
                    if attached_tgt:
                        u32.AttachThreadInput(self_thread, target_thread, False)
                    if attached_fg:
                        u32.AttachThreadInput(self_thread, fg_thread, False)

                log("重试激活窗口... (%d/%d)" % (attempt + 1, max_retries), "INFO")
                time.sleep(0.15)

            log("窗口激活失败，请检查：1)同花顺是否以管理员权限运行而本程序不是；"
                "2)同花顺窗口是否被遮挡或最小化到托盘；3)手动将同花顺窗口置于前台后重试",
                "ERROR")
            return False

        except Exception as e:
            log("激活窗口失败: %s" % e, "ERROR")
            return False
    
    def _send_key(self, vk, down=True):
        """通过 PostMessageW 发送按键消息（备用方案）
        
        参数：
            vk: int，虚拟键码
            down: bool，True表示按下，False表示释放
        """
        if not self.ths_hwnd:
            return
        if down:
            scan = self._user32.MapVirtualKeyW(vk, 0)
            lparam = (scan << 16) | 1
            self._user32.PostMessageW(self.ths_hwnd, _WM_KEYDOWN, vk, lparam)
        else:
            scan = self._user32.MapVirtualKeyW(vk, 0)
            lparam = (scan << 16) | 1 | (1 << 30) | (1 << 31)
            self._user32.PostMessageW(self.ths_hwnd, _WM_KEYUP, vk, lparam)
    
    def _send_input_key(self, vk, down=True):
        """通过 SendInput 发送键盘事件

        使用 SendInput API 模拟真实键盘输入

        参数：
            vk: int，虚拟键码
            down: bool，True表示按下，False表示释放
        """
        scan_code = self._user32.MapVirtualKeyW(vk, 0)
        flags = 0 if down else KEYEVENTF_KEYUP

        ki = KEYBDINPUT()
        ki.wVk = vk
        ki.wScan = scan_code
        ki.dwFlags = flags
        ki.time = 0
        ki.dwExtraInfo = None

        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki = ki

        self._user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
        self._user32.SendInput.restype = ctypes.c_uint
        self._user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    
    def _press_key(self, vk, hold=0.05, use_postmessage=False):
        """模拟按下并释放一个按键
        
        参数：
            vk: int，虚拟键码
            hold: float，按键按住时间（秒）
            use_postmessage: bool，True时用PostMessage后台发送（无需窗口前台），False时用SendInput
        """
        if use_postmessage:
            self._send_key(vk, down=True)
            time.sleep(hold)
            self._send_key(vk, down=False)
            time.sleep(0.03)
        else:
            self._send_input_key(vk, down=True)
            time.sleep(hold)
            self._send_input_key(vk, down=False)
            time.sleep(0.03)
    
    def _type_digit(self, ch, use_postmessage=False):
        """输入单个数字字符
        
        参数：
            ch: str，单个数字字符（'0'-'9'）
            use_postmessage: bool，是否用PostMessage后台发送
        """
        digit = int(ch)
        vk = _VK_0 + digit
        self._press_key(vk, hold=0.04, use_postmessage=use_postmessage)
    
    def _type_string(self, s, use_postmessage=False):
        """输入字符串（支持数字、字母和小数点）
        
        参数：
            s: str，要输入的字符串
            use_postmessage: bool，是否用PostMessage后台发送
        
        处理逻辑：
        - 数字：直接转换为虚拟键码输入
        - 小数点：使用 VK_DECIMAL (0xBE) 输入
        - 字母：根据大小写状态处理 Shift 键
        """
        for ch in str(s):
            if ch.isdigit():
                self._type_digit(ch, use_postmessage=use_postmessage)
            elif ch == '.':
                self._press_key(0xBE, hold=0.04, use_postmessage=use_postmessage)  # VK_DECIMAL 小数点
            elif ch.isalpha():
                vk = ord(ch.upper())
                if vk >= ord('A') and vk <= ord('Z'):
                    vk = vk - ord('A') + 0x41
                    # 检查当前 Shift 键状态
                    shift_state = ctypes.windll.user32.GetKeyState(0x10)
                    need_shift = (ch.isupper() and (shift_state & 0x8000) == 0) or \
                                 (ch.islower() and (shift_state & 0x8000) != 0)
                    if need_shift:
                        if use_postmessage:
                            self._send_key(0x10, down=True)
                        else:
                            self._send_input_key(0x10, down=True)  # 按下 Shift
                    self._press_key(vk, hold=0.04, use_postmessage=use_postmessage)
                    if need_shift:
                        if use_postmessage:
                            self._send_key(0x10, down=False)
                        else:
                            self._send_input_key(0x10, down=False)  # 释放 Shift
            time.sleep(0.02)
    
    def place_order(self, stock_code, stock_name, direction, amount, price=None):
        """执行下单操作（主入口）
        
        参数：
            stock_code: str，股票代码（6位）
            stock_name: str，股票名称（可选）
            direction: int，方向（1=买入，-1=卖出）
            amount: int，下单数量（股）
            price: float，下单价格（已忽略，由同花顺界面自动填充）
        
        返回：
            bool，下单是否成功
        
        执行流程：
        1. 查找同花顺窗口
        2. 激活窗口到前台
        3. 根据配置选择下单模式
        4. 执行下单操作（不输入价格，使用界面自动填充）
        """
        with self._lock:
            try:
                # 1. 查找同花顺窗口
                windows = self.find_ths_windows()
                if not windows:
                    user_kw = self.config.get("window_title_keyword", "").strip()
                    if user_kw:
                        log("未找到标题含'%s'的窗口! 请确认同花顺已启动并登录" % user_kw, "ERROR")
                    else:
                        log("未找到下单客户端窗口! 请先启动同花顺下单客户端(xiadan.exe)并登录", "ERROR")
                    return False
                
                self.ths_hwnd, title = windows[0]
                log("锁定下单窗口: %s (HWND=%d)" % (title, self.ths_hwnd))

                # 2. 先用PostMessage发ESC关闭可能残留的弹窗（不需要前台焦点）
                self._send_key(_VK_ESCAPE, down=True)
                self._send_key(_VK_ESCAPE, down=False)
                time.sleep(0.3)

                # 3. 激活窗口
                activated = self._activate(self.ths_hwnd)
                use_postmessage = False
                if not activated:
                    log("窗口激活失败，降级为 PostMessage 后台按键模式", "WARNING")
                    use_postmessage = True
                else:
                    log("窗口已激活到前台", "OK")

                # 3. 配置参数
                mode = self.config.get("order_mode", "quick")
                delay = float(self.config.get("key_delay", 0.3))
                operate = "买入" if direction == 1 else "卖出"

                # 4. 执行下单（price 参数已忽略，使用界面自动填充价格）
                if mode == "function_key":
                    success = self._order_by_function_key(stock_code, direction, amount, delay, use_postmessage=use_postmessage)
                else:
                    success = self._order_quick(stock_code, direction, amount, delay, use_postmessage=use_postmessage)

                # 5. 结果记录
                if success:
                    self.order_count += 1
                    log("键盘下单完成: %s %s %d股 (累计%d单)" % (
                        stock_code, operate, amount, self.order_count), "OK")
                return success
            
            except Exception as e:
                log("键盘下单异常: %s" % e, "ERROR")
                import traceback
                log(traceback.format_exc(), "ERROR")
                return False
    
    def _parse_account_info(self, text):
        """解析账户信息文本（控件读取模式，字段名和值分开）
        
        参数：
            text: str，控件读取的文本
            
        返回：
            dict，解析后的账户信息
        """
        account_info = {}
        
        field_mapping = {
            "可取金额": "withdrawable",
            "持仓盈亏": "position_pnl",
            "冻结金额": "frozen",
            "股票市值": "stock_market_value",
            "可用金额": "available",
            "总资产": "total_asset",
            "总 资 产": "total_asset",
            "A股可用": "available",
            "当日盈亏": "daily_pnl"
        }
        
        import re
        
        lines = text.strip().split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            for field_name, field_key in field_mapping.items():
                if field_name in line:
                    if i + 1 < len(lines):
                        value_line = lines[i + 1].strip()
                        match = re.search(r'-?[\d,]+(\.\d+)?', value_line)
                        if match:
                            value_str = match.group().replace(',', '')
                            try:
                                value = float(value_str)
                                if field_key not in account_info or value != 0:
                                    account_info[field_key] = value
                            except ValueError:
                                pass
        
        if 'available' in account_info and 'fund_balance' not in account_info:
            account_info['fund_balance'] = account_info['available']
        
        return account_info
    
    def _get_window_text(self, hwnd):
        """获取指定窗口的文本内容
        
        参数：
            hwnd: int，窗口句柄
            
        返回：
            str，窗口文本
        """
        try:
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return ""
            
            buffer = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
            
            return buffer.value
        except Exception as e:
            return ""
    
    def _get_control_text(self, hwnd, text_list):
        """递归遍历子控件，收集所有文本
        
        参数：
            hwnd: int，窗口句柄
            text_list: list，用于收集文本的列表
        """
        try:
            text = self._get_window_text(hwnd)
            if text:
                text_list.append(text)
            
            def callback(child_hwnd, lparam):
                self._get_control_text(child_hwnd, text_list)
                return True
            
            ctypes.windll.user32.EnumChildWindows(hwnd, ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(callback), 0)
        except Exception as e:
            pass
    
    def query(self):
        """查询账户信息（通过Windows API读取控件文本）
        
        流程：
        1. 查找并激活同花顺窗口
        2. 按 F4 切换到账户查询面板
        3. 等待 5 秒让界面刷新（卖出后资金到账有延迟）
        4. 遍历窗口控件读取文本
        5. 解析账户信息字段
        
        优点：准确率接近100%，不受DPI、分辨率、配色影响
        
        返回：
            dict，账户信息（失败返回空字典）
        """
        try:
            log("📊 查询账户信息（控件读取模式）...")
            
            windows = self.find_ths_windows()
            if not windows:
                log("未找到下单客户端窗口!", "ERROR")
                return {}

            self.ths_hwnd, title = windows[0]
            log("锁定窗口: %s (HWND=%d)" % (title, self.ths_hwnd))

            # 先用PostMessage发ESC关闭残留弹窗（不需要前台焦点）
            # 卖出后THS可能弹出确认对话框，阻止窗口激活
            log("按ESC清除残留弹窗")
            self._send_key(_VK_ESCAPE, down=True)
            self._send_key(_VK_ESCAPE, down=False)
            time.sleep(0.3)

            # 尝试激活窗口
            activated = self._activate(self.ths_hwnd)
            if activated:
                log("窗口已激活到前台", "OK")
                use_postmessage = False
            else:
                log("窗口激活失败，改用PostMessage发送按键", "WARNING")
                use_postmessage = True

            # 再次按ESC确保弹窗已关闭
            if use_postmessage:
                self._send_key(_VK_ESCAPE, down=True)
                self._send_key(_VK_ESCAPE, down=False)
            else:
                self._press_key(_VK_ESCAPE)
            time.sleep(0.3)

            log("按F4查询账户信息")
            if use_postmessage:
                self._send_key(_VK_F4, down=True)
                self._send_key(_VK_F4, down=False)
            else:
                self._press_key(_VK_F4, hold=0.1)

            log("等待界面刷新（5秒）...")
            time.sleep(5)
            
            log("遍历窗口控件，读取文本...")
            text_list = []
            self._get_control_text(self.ths_hwnd, text_list)
            
            log("控件文本列表 (%d项):" % len(text_list))
            all_text = "\n".join(text_list)
            
            account_info = self._parse_account_info(all_text)
            
            if account_info:
                log("✅ 账户信息查询完成（控件读取模式）", "OK")
                log("   ├─ 资金余额: %.2f" % account_info.get('fund_balance', 0), "OK")
                log("   ├─ 可用金额: %.2f" % account_info.get('available', 0), "OK")
                log("   ├─ 可取金额: %.2f" % account_info.get('withdrawable', 0), "OK")
                log("   ├─ 股票市值: %.2f" % account_info.get('stock_market_value', 0), "OK")
                log("   ├─ 持仓盈亏: %.2f" % account_info.get('position_pnl', 0), "OK")
                log("   └─ 总资产: %.2f" % account_info.get('total_asset', 0), "OK")
            else:
                log("❌ 控件读取未找到账户信息", "WARNING")
            
            return account_info
            
        except Exception as e:
            log("控件读取异常: %s" % e, "ERROR")
            import traceback
            log(traceback.format_exc(), "ERROR")
            return {}
    

    
    def _order_quick(self, stock_code, direction, amount, delay, use_postmessage=False):
        """快速交易模式下单（无价格输入版）
        
        操作流程：
        1. ESC 清除当前输入
        2. F1（买入）或 F2（卖出）进入对应交易界面
        3. 输入股票代码
        4. Tab 跳过价格框（使用界面自动填充的价格）
        5. Tab 跳转到数量框
        6. 输入数量
        7. Enter 确认下单
        
        说明：
        - 卖出时按两次 F2，确保切换到卖出界面
        - 不输入价格，由同花顺界面自动填充（买入=卖二价，卖出=买二价）
        - use_postmessage=True 时用 PostMessage 后台发送按键（无需窗口前台）
        
        参数：
            stock_code: str，股票代码
            direction: int，方向（1=买入，-1=卖出）
            amount: int，数量
            delay: float，按键间隔
            use_postmessage: bool，是否用PostMessage后台发送
        
        返回：
            bool，操作是否成功
        """
        log("  [快速交易] 按ESC清除")
        self._press_key(_VK_ESCAPE, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)

        if direction == 1:
            # 买入：按两次F1确保进入买入界面
            log("  [快速交易] 买入模式：按F1进入买入界面")
            self._press_key(_VK_F1, hold=0.1, use_postmessage=use_postmessage)
            time.sleep(0.3)
            self._press_key(_VK_F1, hold=0.1, use_postmessage=use_postmessage)
            log("  [快速交易] 再次按F1确保切换到买入界面")
            time.sleep(delay * 2)
            log("  [快速交易] 输入代码: %s" % stock_code)
            self._type_string(stock_code, use_postmessage=use_postmessage)
            time.sleep(delay)
        else:
            # 卖出：按两次F2确保进入卖出界面
            log("  [快速交易] 卖出模式：按F2进入卖出界面")
            self._press_key(_VK_F2, hold=0.1, use_postmessage=use_postmessage)
            time.sleep(0.3)
            self._press_key(_VK_F2, hold=0.1, use_postmessage=use_postmessage)
            log("  [快速交易] 再次按F2确保切换到卖出界面")
            time.sleep(delay * 2)
            log("  [快速交易] 输入代码: %s" % stock_code)
            self._type_string(stock_code, use_postmessage=use_postmessage)
            time.sleep(delay)

        log("  [快速交易] 按Tab跳过价格框（使用界面自动填充价格）")
        self._press_key(_VK_TAB, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)

        log("  [快速交易] 按Tab跳到数量框")
        self._press_key(_VK_TAB, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)

        log("  [快速交易] 输入数量: %d" % amount)
        self._type_string(str(amount), use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)

        log("  [快速交易] 按回车确认下单")
        self._press_key(_VK_RETURN, use_postmessage=use_postmessage)
        time.sleep(0.8)

        log("  [快速交易] 按回车确认弹窗")
        self._press_key(_VK_RETURN, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)
        return True
    
    def _order_by_function_key(self, stock_code, direction, amount, delay, use_postmessage=False):
        """功能键模式下单（F1买入/F2卖出，无价格输入版）
        
        操作流程：
        1. ESC 清除当前输入
        2. F1/F2 进入买入/卖出界面
        3. 输入股票代码
        4. Tab 跳过价格框（使用界面自动填充的价格）
        5. Tab 跳转到数量框
        6. 输入数量
        7. Enter 确认下单
        
        说明：
        - 卖出时按 F2 后额外等待 0.3 秒，确保界面切换完成
        - 不输入价格，由同花顺界面自动填充（买入=卖二价，卖出=买二价）
        - use_postmessage=True 时用 PostMessage 后台发送按键（无需窗口前台）
        
        参数：
            stock_code: str，股票代码
            direction: int，方向（1=买入，-1=卖出）
            amount: int，数量
            delay: float，按键间隔
            use_postmessage: bool，是否用PostMessage后台发送
        
        返回：
            bool，操作是否成功
        """
        log("  [功能键] 按ESC清除")
        self._press_key(_VK_ESCAPE, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)

        # 选择买入或卖出界面
        if direction == 1:
            log("  [功能键] 按F1进入买入界面")
            self._press_key(_VK_F1, hold=0.1, use_postmessage=use_postmessage)
            time.sleep(0.3)
            self._press_key(_VK_F1, hold=0.1, use_postmessage=use_postmessage)
            log("  [功能键] 再次按F1确保切换到买入界面")
        else:
            log("  [功能键] 按F2进入卖出界面")
            self._press_key(_VK_F2, hold=0.1, use_postmessage=use_postmessage)
            time.sleep(0.3)
            self._press_key(_VK_F2, hold=0.1, use_postmessage=use_postmessage)
            log("  [功能键] 再次按F2确保切换到卖出界面")
        time.sleep(delay * 2)

        log("  [功能键] 输入代码: %s" % stock_code)
        self._type_string(stock_code, use_postmessage=use_postmessage)
        time.sleep(delay)

        log("  [功能键] 按Tab跳过价格框（使用界面自动填充价格）")
        self._press_key(_VK_TAB, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)

        log("  [功能键] 按Tab跳到数量框")
        self._press_key(_VK_TAB, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)

        log("  [功能键] 输入数量: %d" % amount)
        self._type_string(str(amount), use_postmessage=use_postmessage)
        time.sleep(delay * 2)
        
        log("  [功能键] 按回车确认下单")
        self._press_key(_VK_RETURN, use_postmessage=use_postmessage)
        time.sleep(0.8)

        log("  [功能键] 按回车确认弹窗")
        self._press_key(_VK_RETURN, use_postmessage=use_postmessage)
        time.sleep(delay * 0.5)
        
        return True
    
    def test_connection(self):
        """测试连接（查找并激活窗口）
        
        返回：
            bool，是否找到并激活成功
        """
        windows = self.find_ths_windows()
        if windows:
            hwnd, title = windows[0]
            log("测试成功! 找到下单客户端窗口: %s (HWND=%d)" % (title, hwnd), "OK")
            if self._activate(hwnd):
                log("已激活窗口到前台, 请确认窗口已切换", "OK")
            else:
                log("激活失败, 请手动点击该窗口", "WARN")
            return True
        else:
            log("未找到下单客户端窗口!", "ERROR")
            user_kw = self.config.get("window_title_keyword", "").strip()
            if user_kw:
                log("当前关键词: '%s' 未匹配到任何窗口" % user_kw, "INFO")
            else:
                log("自动匹配未找到窗口, 请先启动同花顺下单客户端", "INFO")
            return False


# ===========================================================================
# HTTP推送执行器
# ===========================================================================
class HttpPushExecutor:
    """HTTP推送执行器
    
    将交易信号通过 HTTP POST 请求推送到跟单控制面板
    
    信号格式：[stock_code, direction, "PythonAuto", amount, follow_ratio]
    
    使用场景：
    - 无法直接操作同花顺客户端时（如远程服务器）
    - 需要通过中间件转发信号时
    """
    
    def __init__(self, config):
        """初始化HTTP执行器
        
        参数：
            config: dict，配置字典
        """
        self.config = config
        self.push_url = config.get("http_push_url", "").strip()
        self.token = config.get("http_token", "").strip()
    
    def place_order(self, stock_code, stock_name, direction, amount):
        """推送交易信号到HTTP服务
        
        参数：
            stock_code: str，股票代码
            stock_name: str，股票名称
            direction: int，方向（1=买入，-1=卖出）
            amount: int，数量
        
        返回：
            bool，推送是否成功
        """
        if not self.push_url:
            log("HTTP推送模式未配置 http_push_url", "ERROR")
            return False

        # 构造信号数据
        signal = [stock_code, direction, "PythonAuto", amount, float(self.config.get("follow_ratio", 1.0))]
        body = json.dumps(signal).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        
        # 添加认证令牌
        if self.token:
            headers["X-Token"] = self.token

        try:
            log("HTTP推送信号: %s" % signal)
            req = urllib.request.Request(self.push_url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("ok"):
                    log("HTTP推送成功: %s" % result, "OK")
                    return True
                else:
                    log("HTTP推送失败: %s" % result.get("msg", "unknown"), "ERROR")
                    return False
        except urllib.error.URLError as e:
            log("HTTP推送连接失败: %s" % e, "ERROR")
            return False
        except Exception as e:
            log("HTTP推送异常: %s" % e, "ERROR")
            return False


# ===========================================================================
# 自动交易器主类
# ===========================================================================
class AutoTrader:
    """自动交易器主类（无价格输入版）
    
    统一入口，根据配置选择执行模式（键盘模拟或HTTP推送）
    不手动输入价格，由同花顺界面自动填充（买入=卖二价，卖出=买二价）
    
    核心方法：
    - trade(): 执行交易下单（不输入价格）
    - buy(): 买入股票（trade的快捷方式）
    - sell(): 卖出股票（trade的快捷方式）
    - test_connection(): 测试连接
    - set_mode(): 设置执行模式
    """
    
    def __init__(self, config=None):
        """初始化交易器
        
        参数：
            config: dict，配置字典（可选，默认从配置文件加载）
        """
        self.config = config or load_config()
        self.key_executor = KeyOrderExecutor(self.config)
        self.http_executor = HttpPushExecutor(self.config)
        
        # 根据配置自动选择执行模式
        self.execution_mode = "keyboard" if not self.config.get("http_push_url") else "http"
        self.order_count = 0
    

    def set_mode(self, mode):
        """设置执行模式
        
        参数：
            mode: str，"keyboard"（键盘模拟）或 "http"（HTTP推送）
        """
        if mode in ("keyboard", "http"):
            self.execution_mode = mode
            log("执行模式已切换为: %s" % ("键盘模拟" if mode == "keyboard" else "HTTP推送"))
        else:
            log("无效模式: %s" % mode, "ERROR")
    
    def query(self):
        """查询账户信息
        
        返回：
            dict，账户信息（失败返回空字典）
        """
        log("=== 查询账户信息 ===")
        if self.execution_mode == "keyboard":
            return self.key_executor.query()
        else:
            log("HTTP模式不支持查询操作", "INFO")
            return {}
    
    def trade(self, stock_code, direction, amount, stock_name="", price=None):
        """执行交易下单（核心方法，无价格输入版）
        
        参数：
            stock_code: str，股票代码（如 "000001" 或 "000001.XSHE"）
            direction: str/int，方向（"buy"/"买入"/1 表示买入；"sell"/"卖出"/-1 表示卖出）
            amount: int/float，下单数量（股）
            stock_name: str，股票名称（可选）
            price: float，下单价格（已忽略，由同花顺界面自动填充）
        
        返回：
            bool，下单是否成功
        
        处理流程：
        1. 标准化股票代码（去除市场后缀）
        2. 标准化交易方向（转换为 1/-1）
        3. 计算实际下单数量（考虑跟单比例）
        4. 调整为100的倍数（A股交易规则）
        5. 根据执行模式调用对应的执行器（不输入价格）
        """
        # 1. 标准化股票代码（去除 .XSHE/.XSHG 后缀）
        stock_code = str(stock_code).strip()
        if "." in stock_code:
            stock_code = stock_code.split(".")[0]

        # 2. 标准化交易方向
        if direction in ("buy", "买入", "B", "Buy"):
            direction = 1
            operate = "买入"
        elif direction in ("sell", "卖出", "S", "Sell"):
            direction = -1
            operate = "卖出"
        elif isinstance(direction, int) and direction in (1, -1):
            operate = "买入" if direction == 1 else "卖出"
        else:
            log("无效方向: %s" % direction, "ERROR")
            return False

        amount = int(amount)

        # 3. 计算实际下单数量（考虑跟单比例）
        ratio = float(self.config.get("follow_ratio", 1.0))
        min_amt = int(self.config.get("min_amount", 100))
        actual_amount = int(amount * ratio)

        # 4. 验证最小下单量
        if actual_amount < min_amt:
            log("下单数量不足%d股, 跳过: %s 原量=%d 比例=%.2f 实际=%d" % (
                min_amt, stock_code, amount, ratio, actual_amount), "WARN")
            return False

        # 5. 调整为100的倍数（A股交易规则：买入必须是100股的整数倍）
        if actual_amount % 100 != 0:
            actual_amount = actual_amount - (actual_amount % 100)
            log("数量调整为100的倍数: %d" % actual_amount, "INFO")

        # 6. 设置股票名称
        if not stock_name:
            stock_name = stock_code

        # 7. 输出下单日志
        log(">>> 下单信号: %s %s %d股 (比例%.2f) [价格由界面自动填充]" % (stock_code, operate, actual_amount, ratio))

        # 8. 执行下单（不传价格，使用界面自动填充）
        if self.execution_mode == "keyboard":
            success = self.key_executor.place_order(stock_code, stock_name, direction, actual_amount)
        else:
            success = self.http_executor.place_order(stock_code, stock_name, direction, actual_amount)

        # 9. 结果记录
        if success:
            self.order_count += 1
            log("<<< 下单成功: %s %s %d股 (累计%d单)" % (stock_code, operate, actual_amount, self.order_count), "OK")
        else:
            log("<<< 下单失败: %s %s %d股" % (stock_code, operate, actual_amount), "ERROR")

        return success
    
    def buy(self, stock_code, amount, stock_name="", price=None):
        """买入股票（trade方法的快捷方式）
        
        参数：
            stock_code: str，股票代码
            amount: int，数量（股）
            stock_name: str，股票名称（可选）
            price: float，下单价格（已忽略，由同花顺界面自动填充）
        
        返回：
            bool，下单是否成功
        """
        return self.trade(stock_code, 1, amount, stock_name, price)
    
    def sell(self, stock_code, amount, stock_name="", price=None):
        """卖出股票（trade方法的快捷方式）
        
        参数：
            stock_code: str，股票代码
            amount: int，数量（股）
            stock_name: str，股票名称（可选）
            price: float，下单价格（已忽略，由同花顺界面自动填充）
        
        返回：
            bool，下单是否成功
        """
        return self.trade(stock_code, -1, amount, stock_name, price)


# ===========================================================================
# 示例策略（模拟交易信号）
# ===========================================================================
def run_demo_strategy(trader):
    """示例策略：模拟一系列交易信号
    
    实际使用时，替换为你自己的策略逻辑：
    1. 从数据源获取行情数据
    2. 根据策略算法计算交易信号
    3. 调用 trader.buy() 或 trader.sell() 执行下单
    
    参数：
        trader: AutoTrader，交易器实例
    """
    log("=== 示例策略开始 ===")

    demo_signals = [
        {"code": "000001", "name": "平安银行", "direction": "buy", "amount": 100},
        {"code": "600036", "name": "招商银行", "direction": "buy", "amount": 200},
        {"code": "000001", "name": "平安银行", "direction": "sell", "amount": 100},
    ]

    for i, signal in enumerate(demo_signals):
        log("\n--- 信号 %d/%d ---" % (i + 1, len(demo_signals)))
        success = trader.trade(
            stock_code=signal["code"],
            direction=signal["direction"],
            amount=signal["amount"],
            stock_name=signal["name"]
        )
        if i < len(demo_signals) - 1:
            log("等待5秒后执行下一笔交易...")
            time.sleep(5)

    log("\n=== 示例策略结束 ===")
    log("累计下单: %d 笔" % trader.order_count)


# ===========================================================================
# 入口函数
# ===========================================================================
def main():
    """命令行入口函数
    
    提供交互式菜单：
    1. 测试下单连接（键盘模式）
    2. 运行示例策略
    3. 退出
    
    运行前请确保：
    - Windows 系统
    - 同花顺客户端已启动并登录
    - 配置文件已正确设置
    """
    print("=" * 60)
    print("Python自动交易器（无价格输入版）")
    print("=" * 60)

    trader = AutoTrader()

    log("当前执行模式: %s" % ("键盘模拟" if trader.execution_mode == "keyboard" else "HTTP推送"))
    log("配置文件: %s" % CONFIG_PATH)

    if trader.execution_mode == "keyboard":
        log("请确认:")
        log("  1. 同花顺客户端(xiadan.exe)已启动并登录")
        log("  2. 窗口标题关键词已正确配置")
        log("  3. 同花顺已设置自动填充卖二/买二价格")
        log("")
        log("执行步骤:")
        log("  1. 先运行 test_connection() 测试连接")
        log("  2. 确认连接正常后运行 run_demo_strategy()")
        log("")

        while True:
            print("\n请选择操作:")
            print("  1. 测试下单连接")
            print("  2. 运行示例策略")
            print("  3. 退出")
            choice = input("输入选择 (1/2/3): ").strip()

            if choice == "1":
                trader.test_connection()
            elif choice == "2":
                print("\n警告: 此操作会在同花顺中实际下单!")
                confirm = input("确认继续吗? (y/N): ").strip().lower()
                if confirm == "y":
                    run_demo_strategy(trader)
                else:
                    log("已取消", "INFO")
            elif choice == "3":
                log("退出程序", "INFO")
                break
            else:
                print("无效选择")
    else:
        # HTTP推送模式
        log("HTTP推送模式:")
        log("  推送地址: %s" % trader.http_executor.push_url)
        log("  请确保跟单控制面板已启动并监听该端口")
        log("")
        print("请选择操作:")
        print("  1. 运行示例策略")
        print("  2. 退出")
        choice = input("输入选择 (1/2): ").strip()

        if choice == "1":
            run_demo_strategy(trader)
        elif choice == "2":
            log("退出程序", "INFO")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("用户中断", "INFO")
    except Exception as e:
        log("程序异常: %s" % e, "ERROR")
        import traceback
        traceback.print_exc()