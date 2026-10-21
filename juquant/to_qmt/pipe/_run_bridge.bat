@echo off
cd /d "%~dp0"
python -u external_redis_bridge.py >> external_redis_bridge.log 2>&1