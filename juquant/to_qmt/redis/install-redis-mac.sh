#!/bin/bash

# ============================================
# 配置区 - 可按需修改
# ============================================
REDIS_PASSWORD="1A2B3C4D"   # 请务必修改为强密码
REDIS_PORT="6379"
SERVICE_NAME="redis"
# ============================================

# 颜色定义（提升可读性）
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}[INFO] 当前工作目录：$(pwd)${NC}"
echo ""

# ============================================
# 第一步：检查是否已安装 Redis
# ============================================
if command -v redis-server &> /dev/null; then
    INSTALL_PATH=$(which redis-server)
    echo -e "${YELLOW}[INFO] Redis 已安装，路径：${INSTALL_PATH}${NC}"
    
    # 检查是否已作为服务注册
    if brew services list | grep -q "redis.*started"; then
        echo -e "${YELLOW}[INFO] Redis 服务已在后台运行，无需重复安装。${NC}"
    elif brew services list | grep -q "redis.*stopped"; then
        echo -e "${YELLOW}[INFO] Redis 已安装但服务未启动，正在启动...${NC}"
        brew services start redis
    else
        echo -e "${YELLOW}[INFO] Redis 已安装，但未通过 Homebrew 注册服务。${NC}"
        echo -e "${YELLOW}[提示] 如需重新安装，请先手动卸载：brew uninstall redis${NC}"
    fi
    exit 0
fi

# ============================================
# 第二步：检查 Homebrew 是否安装
# ============================================
if ! command -v brew &> /dev/null; then
    echo -e "${RED}[ERROR] 未找到 Homebrew，请先安装 Homebrew：${NC}"
    echo '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

# ============================================
# 第三步：下载并安装 Redis（Homebrew）
# ============================================
echo -e "${GREEN}[INFO] 正在通过 Homebrew 安装 Redis（包含下载和编译）...${NC}"
brew install redis

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Redis 安装失败，请检查网络或 Homebrew 状态。${NC}"
    exit 1
fi
echo -e "${GREEN}[INFO] Redis 安装完成！${NC}"
echo ""

# ============================================
# 第四步：设置 Redis 密码（修改配置文件）
# ============================================
# 获取 Redis 安装前缀路径（自动适配 Intel 和 Apple Silicon）
REDIS_PREFIX=$(brew --prefix redis)
CONF_FILE="${REDIS_PREFIX}/etc/redis.conf"

echo -e "${GREEN}[INFO] 配置文件路径：${CONF_FILE}${NC}"

if [ -f "$CONF_FILE" ]; then
    # 先备份配置文件（以防万一）
    cp "$CONF_FILE" "${CONF_FILE}.bak"
    
    # 取消注释并强制设置 requirepass
    # - 先替换已存在但被注释掉的行
    sed -i '' "s/^# *requirepass .*/requirepass ${REDIS_PASSWORD}/" "$CONF_FILE"
    
    # - 如果文件中完全没有 requirepass 行，则追加一行
    if ! grep -q "^requirepass" "$CONF_FILE"; then
        echo "requirepass ${REDIS_PASSWORD}" >> "$CONF_FILE"
    fi
    
    echo -e "${GREEN}[INFO] Redis 密码已设置为：${REDIS_PASSWORD}${NC}"
else
    echo -e "${RED}[WARN] 未找到配置文件：${CONF_FILE}，请手动配置密码。${NC}"
fi
echo ""

# ============================================
# 第五步：启动 Redis 后台服务（开机自启）
# ============================================
echo -e "${GREEN}[INFO] 正在注册并启动 Redis 后台服务...${NC}"
brew services start redis

if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] 服务启动失败！请检查日志。${NC}"
    exit 1
fi

echo -e "${GREEN}[INFO] Redis 服务启动成功！${NC}"
echo ""

# ============================================
# 安装完成信息汇总
# ============================================
echo "============================================"
echo -e "  ${GREEN}Redis 安装完成！${NC}"
echo "  服务名称：${SERVICE_NAME}"
echo "  监听端口：${REDIS_PORT}"
echo "  访问密码：${REDIS_PASSWORD}"
echo "  安装目录：${REDIS_PREFIX}"
echo "  配置文件：${CONF_FILE}"
echo "============================================"
echo ""
echo -e "${GREEN}[提示] 可以使用以下命令连接 Redis：${NC}"
echo "  redis-cli -h 127.0.0.1 -p ${REDIS_PORT} -a ${REDIS_PASSWORD}"
echo ""
echo -e "${GREEN}[提示] 管理服务命令：${NC}"
echo "  启动服务：brew services start redis"
echo "  停止服务：brew services stop redis"
echo "  重启服务：brew services restart redis"
echo "  查看状态：brew services list | grep redis"
echo ""