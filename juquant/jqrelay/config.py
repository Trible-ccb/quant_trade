# -*- coding: utf-8 -*-
"""
聚宽→Redis→执行端 全链路配置
"""
import os

# ==================== Redis配置 ====================
REDIS_HOST = "127.0.0.1"
REDIS_PORT = 6379
REDIS_PASSWORD = "自己设的redis密码"  # 生产环境设置强密码
REDIS_DB = 0
REDIS_DECODE_RESPONSES = True

# ==================== Stream配置 ====================
# 策略名 → Stream Key 映射（与fangan1一致，按策略分Stream）
STREAM_KEYS = {
    "S1_4ETF轮动":    "jq:stream:s1_etf4",
    "S2_4支红利":     "jq:stream:s2_hongli",
    "S3_QDII套利":    "jq:stream:s3_qdii",
    "S4_博收益ETF":   "jq:stream:s4_boyishouyi",
    "S5_小市值":      "jq:stream:s5_small",
    "default":        "jq:stream:default",
}
# Consumer Group名称
CONSUMER_GROUP = "jq_executors"
# Consumer名称（每台服务器唯一）
CONSUMER_NAME = "executor_01"
# Stream消息保留时长（秒）：已ACK的消息7天后清理
STREAM_MAXLEN = 5000
# XREADGROUP阻塞超时（毫秒），0=无限等待
BLOCK_TIMEOUT_MS = 0

# ==================== 执行端配置 ====================
# 执行端类型: "qmt" 或 "ths"
EXECUTOR_TYPE = "qmt"

# QMT配置（miniQMT模式）
QMT_PATH = r'C:\QMT\国金证券QMT交易端\userdata_mini'
QMT_ACCOUNT = '你的QMT账号'       # 填入你的资金账号
QMT_ACCOUNT_TYPE = "STOCK"
QMT_CONNECT_TIMEOUT = 60

# 同花顺配置（备用）
THS_EXE_PATH = r"C:\同花顺\xiadan.exe"

# ==================== 风控配置 ====================
RISK = {
    # 单票最大仓位比例（占总资产）
    "max_single_position_pct": 0.30,
    # 单日最大下单次数（每个Stream），0=不限制
    "max_daily_orders_per_stream": 300,
    # 单笔最大金额（元），0=不限制
    "max_single_order_value": 0,
    # 涨跌停过滤：True=不追涨跌停
    "filter_limit_up_down": True,
    # 集合竞价期间不下单（9:15-9:25）
    "skip_auction_period": True,
    # 最小下单间隔（秒），防止短时间内重复下单同一标的
    "min_order_interval_sec": 2,
}

# ==================== 持仓查询API（供影子对账使用） ====================
# 聚宽侧通过Redis请求-响应模式查询执行端持仓
# 请求Key: jq:query:positions_request
# 响应Key: jq:query:positions_response
QUERY_POSITIONS_REQ_KEY = "jq:query:positions_request"
QUERY_POSITIONS_RESP_KEY = "jq:query:positions_response"
QUERY_TIMEOUT_SEC = 10

# ==================== 去重配置 ====================
# 已处理消息ID的Redis Set Key
DEDUP_SET_KEY = "jq:processed_msg_ids"
# 去重Set过期时间（秒）：3天
DEDUP_TTL_SEC = 3 * 24 * 3600

# ==================== 日志配置 ====================
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_LEVEL = "INFO"
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 30

# ==================== 交易时间 ====================
TRADING_MORNING_START = "09:30"
TRADING_MORNING_END = "11:30"
TRADING_AFTERNOON_START = "13:00"
TRADING_AFTERNOON_END = "15:00"