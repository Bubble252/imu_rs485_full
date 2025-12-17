#!/bin/bash
# ============================================
# SSH隧道建立脚本
# 用于通过跳板机连接远程B服务器
# 参考: whole3_2/使用说明.md
# ============================================

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
KEYS_DIR="$PROJECT_DIR/keys"

# 配置参数 (新跳板机 - 2024年12月更新)
PROXY_HOST="root@202.112.113.15"
PROXY_PORT="2228"
PROXY_KEY="$KEYS_DIR/scorpio_jump_2228.txt"

TARGET_HOST="root@202.112.113.74"
TARGET_PORT="2237"
TARGET_KEY="$KEYS_DIR/capri_yhx_2237"

# 端口转发配置 (与 triple 文件一致，共6个端口)
# 5555: 控制数据 A → B (PUSH)
# 5556: 保留
# 5557: 视频 B → A (SUB)
# 5558: 保留
# 5559: LeRobot数据 A → LeRobot (PUSH)
# 5561: 音频 B → A (SUB)
PORTS="5555 5556 5557 5558 5559 5561"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  SSH隧道建立脚本 (完整版)${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "配置信息:"
echo "  跳板机: $PROXY_HOST:$PROXY_PORT"
echo "  目标机: $TARGET_HOST:$TARGET_PORT"
echo "  转发端口: $PORTS"
echo ""

# 检查密钥文件
if [ ! -f "$PROXY_KEY" ]; then
    echo -e "${RED}错误: 跳板机密钥文件不存在: $PROXY_KEY${NC}"
    exit 1
fi
if [ ! -f "$TARGET_KEY" ]; then
    echo -e "${RED}错误: 目标机密钥文件不存在: $TARGET_KEY${NC}"
    exit 1
fi

# 设置密钥权限
chmod 600 "$PROXY_KEY" "$TARGET_KEY" 2>/dev/null || true

# 检查是否已有隧道在运行
PORTS_IN_USE=""
for PORT in $PORTS; do
    if lsof -i :$PORT > /dev/null 2>&1; then
        PORTS_IN_USE="$PORTS_IN_USE $PORT"
    fi
done

if [ -n "$PORTS_IN_USE" ]; then
    echo -e "${YELLOW}警告: 以下端口已被占用:$PORTS_IN_USE${NC}"
    echo "检查占用进程:"
    for PORT in $PORTS_IN_USE; do
        lsof -i :$PORT
    done
    echo ""
    read -p "是否终止现有进程? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for PORT in $PORTS_IN_USE; do
            lsof -i :$PORT | awk 'NR>1 {print $2}' | xargs kill -9 2>/dev/null || true
        done
        sleep 1
        echo -e "${GREEN}已终止现有进程${NC}"
    else
        echo "退出"
        exit 1
    fi
fi

# 构建端口转发参数
PORT_FORWARDS=""
for PORT in $PORTS; do
    PORT_FORWARDS="$PORT_FORWARDS -L $PORT:localhost:$PORT"
done

# 建立SSH隧道
echo -e "${GREEN}正在建立SSH隧道...${NC}"

# SSH命令: 通过跳板机连接目标机，并建立端口转发
SSH_CMD="ssh -f -N $PORT_FORWARDS \
    -i $TARGET_KEY -p $TARGET_PORT \
    -o \"ProxyCommand ssh -i $PROXY_KEY -p $PROXY_PORT -W %h:%p $PROXY_HOST\" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    $TARGET_HOST"

echo "命令: $SSH_CMD"
echo ""

eval $SSH_CMD

# 检查是否成功
sleep 2
SUCCESS=true
for PORT in $PORTS; do
    if ! lsof -i :$PORT > /dev/null 2>&1; then
        echo -e "${RED}端口 $PORT 未能建立${NC}"
        SUCCESS=false
    fi
done

if $SUCCESS; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  SSH隧道建立成功! (6个端口)${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo ""
    echo "隧道信息:"
    echo "  5555: 控制数据 (A → B)"
    echo "  5556: 保留"
    echo "  5557: 视频流 (B → A)"
    echo "  5558: 保留"
    echo "  5559: LeRobot数据"
    echo "  5561: 音频流 (B → A)"
    echo ""
    echo "验证隧道:"
    echo "  ss -tuln | grep -E '5555|5556|5557|5558|5559|5561'"
    echo ""
    echo "现在可以运行主程序:"
    echo "  cd $PROJECT_DIR && python main.py"
else
    echo -e "${RED}部分SSH隧道建立失败${NC}"
    exit 1
fi
