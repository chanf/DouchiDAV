#!/bin/bash
# 自动部署：scp 上传 ipk 到软路由 → opkg 安装 → 重启 webdav 服务
# 用法：先 python3 build_ipk.py，再 ./deploy.sh
# 请把下面 PASSWORD 改成你的路由器 root 密码
PASSWORD="你的路由器密码"
ROUTER_IP="192.168.66.1"
ROUTER_USER="root"
ROUTER_PATH="/tmp/"

# 1. 找最新构建包（前缀 webdav）
LATEST_IPK=$(ls -t dist/luci-app-sswebdav_*.ipk 2>/dev/null | head -n 1)
[ -z "$LATEST_IPK" ] && { echo "错误：未找到 ipk，请先 python3 build_ipk.py"; exit 1; }
IPK_BASENAME=$(basename "$LATEST_IPK")
echo "部署：$IPK_BASENAME -> $ROUTER_USER@$ROUTER_IP"

# 2. expect 自动填密码，scp 上传
expect -c "
spawn scp \"$LATEST_IPK\" \"$ROUTER_USER@$ROUTER_IP:$ROUTER_PATH\"
expect {
    \"*yes/no*\" { send \"yes\r\"; exp_continue }
    \"*password:*\" { send \"$PASSWORD\r\" }
}
expect eof
catch wait result
exit [lindex \$result 3]
"

# 3. ssh 远程 opkg 安装并重启 webdav 服务
expect -c "
spawn ssh \"$ROUTER_USER@$ROUTER_IP\" \"opkg install /tmp/$IPK_BASENAME && /etc/init.d/webdav restart\"
expect {
    \"*yes/no*\" { send \"yes\r\"; exp_continue }
    \"*password:*\" { send \"$PASSWORD\r\" }
}
expect eof
catch wait result
exit [lindex \$result 3]
"
