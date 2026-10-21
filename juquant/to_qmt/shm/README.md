部署与运行说明
启动外部桥接进程：
在 QMT 之外（如本机命令行或其他服务器），运行 python external_redis_bridge.py。它会创建名为 QMT_SIGNAL_SHM 的共享内存，并开始消费 Redis 信号。

启动 QMT 策略：
将改造后的 handle_orders.py 放入 QMT 内置 Python 策略中运行。QMT 进程会自动附加到已有的共享内存。

信号流转路径：
聚宽拦截器 -> Redis -> external_redis_bridge.py -> 共享内存 -> QMT内置策略 -> passorder

ECS端下载代码命令：
curl.exe -L -o shm_download_oss.bat "https://ccb-files-bucket.oss-cn-beijing.aliyuncs.com/shm_download_oss.bat"; .\shm_download_oss.bat
