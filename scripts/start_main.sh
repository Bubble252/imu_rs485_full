#!/bin/bash
# ============================================
# 主程序启动脚本
# 在lerobot环境中运行IMU控制系统
# ============================================

set -e

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  IMU机械臂控制系统 - 主程序${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查conda环境
if ! command -v conda &> /dev/null; then
    echo -e "${RED}错误: 未找到conda命令${NC}"
    exit 1
fi

# 激活lerobot环境
echo -e "${GREEN}激活 lerobot 环境...${NC}"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate lerobot || {
    echo -e "${RED}错误: 无法激活 lerobot 环境${NC}"
    echo "请确保已创建 lerobot conda环境"
    echo "  conda create -n lerobot python=3.10"
    exit 1
}

echo -e "${GREEN}当前环境: $(conda info --envs | grep '*' | awk '{print $1}')${NC}"
echo ""

# 检查SSH隧道 (如果配置启用)
LOCAL_PORT=5555
if lsof -i :$LOCAL_PORT > /dev/null 2>&1; then
    echo -e "${GREEN}✓ SSH隧道已就绪 (端口 $LOCAL_PORT)${NC}"
else
    echo -e "${YELLOW}! SSH隧道未建立${NC}"
    echo "  如需远程连接，请先运行: ./scripts/setup_tunnel.sh"
    echo ""
fi

# 检查串口
SERIAL_PORT="/dev/ttyUSB0"
if [ -e "$SERIAL_PORT" ]; then
    echo -e "${GREEN}✓ IMU串口已就绪 ($SERIAL_PORT)${NC}"
else
    echo -e "${YELLOW}! IMU串口未找到 ($SERIAL_PORT)${NC}"
    echo "  请检查USB连接"
    echo ""
    # 尝试查找其他串口
    echo "可用串口:"
    ls -la /dev/ttyUSB* 2>/dev/null || echo "  无可用串口"
    echo ""
fi

# 切换到项目目录
cd "$PROJECT_DIR"

echo ""
echo -e "${GREEN}启动主程序...${NC}"
echo ""

# 运行主程序
python main.py "$@"
