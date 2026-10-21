# 在这行代码from jqdata import * 后面粘贴以下代码块

# =======================实盘配置Start=======================================
MODE = 'live'  # 可选值：'live'（实盘下单）、'其他值'（聚宽模拟盘下单）
if 'live' == MODE:
    from redis_signal_interceptor import RedisSignalInterceptor
    # 创建拦截器实例并安装
    interceptor = RedisSignalInterceptor()
    (order,order_target,order_value,order_target_value) = interceptor.wrap_orders(order,order_target,order_value,order_target_value)
# =======================实盘配置End=======================================
