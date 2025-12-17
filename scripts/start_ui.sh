#!/bin/bash
# ============================================
# UI启动脚本
# 在pyqt5_ui环境中运行可视化界面
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
echo -e "${BLUE}  IMU机械臂控制系统 - 可视化UI${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# 检查conda环境
if ! command -v conda &> /dev/null; then
    echo -e "${RED}错误: 未找到conda命令${NC}"
    exit 1
fi

# 激活pyqt5_ui环境
echo -e "${GREEN}激活 pyqt5_ui 环境...${NC}"
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate pyqt5_ui || {
    echo -e "${YELLOW}警告: 无法激活 pyqt5_ui 环境${NC}"
    echo "尝试使用 base 环境..."
    conda activate base
}

echo -e "${GREEN}当前环境: $(conda info --envs | grep '*' | awk '{print $1}')${NC}"
echo ""

# 检查依赖
echo "检查依赖..."
python -c "import PyQt5" 2>/dev/null || {
    echo -e "${YELLOW}警告: PyQt5 未安装${NC}"
    echo "安装依赖: pip install PyQt5 pyqtgraph"
}

python -c "import pyqtgraph" 2>/dev/null || {
    echo -e "${YELLOW}警告: pyqtgraph 未安装${NC}"
}

# 切换到项目目录
cd "$PROJECT_DIR"

echo ""
echo -e "${GREEN}启动UI...${NC}"
echo ""

# 设置Qt环境变量
export QT_QPA_PLATFORM=xcb
export QT_AUTO_SCREEN_SCALE_FACTOR=0

# 运行UI
python -m ui.viewer "$@"
