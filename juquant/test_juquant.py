from jqdatasdk import *
from config_local import JQ_USER, JQ_PASS

# 登录聚宽
auth(JQ_USER, JQ_PASS)
# 测试：获取平安银行最新价格
print(get_price("000001.XSHE", end_date="2026-05-05", count=1))

# 查看剩余数据流量
print(get_query_count())