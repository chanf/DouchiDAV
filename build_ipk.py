#!/usr/bin/env python3
# 豆豉WebDAV 打包脚本：单源真相 src_files → 可复现 .ipk
# 所有交付文件都在下面 src_files 字典里（key=打包相对路径，value=文件内容）。
# 改任何交付文件就改这里，然后 `python3 build_ipk.py`。勿手编 src/（会被覆盖）。
# 骨架（四函数 + main）移植自 luci-app-mihomo，仅替换业务层 + 路径中的 mihomo→webdav。
import os
import tarfile
import io
import shutil
import re

PKG_NAME = "luci-app-webdav"
PKG_VERSION = "2.0.0-16"
PKG_ARCH = "all"
IPK_FILENAME = f"{PKG_NAME}_{PKG_VERSION}_{PKG_ARCH}.ipk"

src_files = {
    # ===================== CONTROL/ =====================
    "CONTROL/control": """Package: luci-app-webdav
Version: 2.0.0-1
Depends: luci-base, curl
Architecture: all
Maintainer: feng
Section: luci
Priority: optional
Description: 豆豉WebDAV - Lightweight WebDAV server (hacdias/webdav) for iStoreOS / OpenWrt
""",
    "CONTROL/postinst": """#!/bin/sh
if [ -z "$IPKG_INSTROOT" ]; then
    rm -f /tmp/luci-indexcache
    rm -f /tmp/luci-modulecache
    (sleep 3; /etc/init.d/rpcd restart) &
fi
exit 0
""",
    "CONTROL/postrm": """#!/bin/sh
if [ -z "$IPKG_INSTROOT" ]; then
    rm -f /tmp/luci-indexcache
    rm -f /tmp/luci-modulecache
    /etc/init.d/rpcd restart
fi
exit 0
""",
    "CONTROL/conffiles": """/etc/config/webdav
""",
    # ===================== root/etc/config/ =====================
    "root/etc/config/webdav": """config webdav 'config'
\toption enabled '0'
\toption port '6065'
\toption root_path '/mnt/sata1'
\toption username 'admin'
\toption password ''
\toption read_only '0'
\toption prefix '/'
""",
    # ===================== root/etc/init.d/ =====================
    "root/etc/init.d/webdav": """#!/bin/sh /etc/rc.common

START=95
USE_PROCD=1

start_service() {
\tconfig_load webdav

\tlocal enabled port root_path username password read_only
\tconfig_get_bool enabled config enabled 0
\tconfig_get port config port "6065"
\tconfig_get root_path config root_path "/mnt/sata1"
\tconfig_get username config username "admin"
\tconfig_get password config password ""
\tconfig_get_bool read_only config read_only 0

\t[ "$enabled" -ne 1 ] && { logger -t webdav "disabled, skip"; return 0; }

\t# 确保核心二进制存在；缺失则按架构下载（沿用 mihomo 模式）
\tlocal core_path
\tcore_path=$(/usr/share/webdav/helper.sh get_core_path)
\tif [ ! -x "$core_path" ]; then
\t\tlogger -t webdav "core binary missing, downloading..."
\t\t/usr/share/webdav/helper.sh download_core || { logger -t webdav "download failed"; return 1; }
\t\tcore_path=$(/usr/share/webdav/helper.sh get_core_path)
\tfi

\t# 确保根目录存在
\tmkdir -p "$root_path"

\t# 用 UCI 选项生成运行配置到 /tmp（RAM），进程读它启动
\t/usr/share/webdav/helper.sh prepare_config || return 1

\t# procd 拉起守护进程：崩溃自动重启
\tprocd_open_instance
\tprocd_set_param command "$core_path" -c /tmp/webdav_run.yaml
\tprocd_set_param stdout 1
\tprocd_set_param stderr 1
\tprocd_set_param respawn
\tprocd_close_instance

\tlogger -t webdav "WebDAV started on port $port, root=$root_path"
}

stop_service() {
\trm -f /tmp/webdav_run.yaml
\tlogger -t webdav "WebDAV stopped"
}

service_triggers() {
\tprocd_add_reload_trigger "webdav"
}
""",

    # ===================== root/usr/share/webdav/ =====================
    "root/usr/share/webdav/helper.sh": """#!/bin/sh
# 豆豉WebDAV 后端：case 分发。配置读取用 uci -q get（无需 source 库）。
# JSON 输出统一用单引号包裹 + 内部双引号字面量 + 变量拼接，避开双重转义。
CORE_VERSION="v5.14.0"
PKG_VERSION="__PKG_VERSION__"
CORE_PATH="/usr/bin/webdav-go"
GITHUB="https://github.com/hacdias/webdav/releases/download"

get_arch() {
    arch=$(uname -m 2>/dev/null)
    case "$arch" in
        x86_64)        echo "amd64" ;;
        aarch64)       echo "arm64" ;;
        armv7l)        echo "armv7" ;;
        armv6l)        echo "armv6" ;;
        armv5tel)      echo "armv5" ;;
        arm*)          echo "armv7" ;;
        mips)          echo "mips" ;;
        mipsel)        echo "mipsle" ;;
        *)             echo "$arch" ;;
    esac
}

download_core() {
    arch=$(get_arch)
    tarball="linux-$arch-webdav.tar.gz"
    url="$GITHUB/$CORE_VERSION/$tarball"
    tmpdir=$(mktemp -d 2>/dev/null || echo "/tmp/webdav_dl")
    mkdir -p "$tmpdir" "$(dirname "$CORE_PATH")"
    if curl -fsSL "$url" -o "$tmpdir/$tarball" 2>/dev/null && \
       tar -xzf "$tmpdir/$tarball" -C "$tmpdir" 2>/dev/null && \
       cp -f "$tmpdir/webdav" "$CORE_PATH" 2>/dev/null; then
        chmod 0755 "$CORE_PATH"
        rm -rf "$tmpdir"
        echo '{"ok":true,"path":"'"$CORE_PATH"'","arch":"'"$arch"'"}'
    else
        rm -rf "$tmpdir"
        echo '{"ok":false,"msg":"下载失败，请检查网络，或手动放置二进制到 '"$CORE_PATH"'"}'
    fi
}

prepare_config() {
    port=$(uci -q get webdav.config.port) || port=6065
    root_path=$(uci -q get webdav.config.root_path) || root_path=/mnt/sata1
    username=$(uci -q get webdav.config.username) || username=admin
    password=$(uci -q get webdav.config.password) || password=""
    read_only=$(uci -q get webdav.config.read_only) || read_only=0
    prefix=$(uci -q get webdav.config.prefix) || prefix=/
    [ "$read_only" = "1" ] && perms="R" || perms="CRUD"
    cat > /tmp/webdav_run.yaml <<EOF
address: 0.0.0.0
port: $port
prefix: $prefix
behindProxy: false
debug: false
directory: $root_path
permissions: $perms
users:
  - username: $username
    password: $password
EOF
}

get_status() {
    port=$(uci -q get webdav.config.port) || port=6065
    root_path=$(uci -q get webdav.config.root_path) || root_path=/mnt/sata1
    if pgrep -f "$CORE_PATH" >/dev/null 2>&1; then running=1; else running=0; fi
    if [ -n "$root_path" ] && [ -d "$root_path" ]; then
        total=$(df -h "$root_path" | awk 'NR==2{print $2}')
        used=$(df -h "$root_path" | awk 'NR==2{print $3}')
        avail=$(df -h "$root_path" | awk 'NR==2{print $4}')
    else
        total="?"; used="?"; avail="?"
    fi
    if [ -f "$CORE_PATH" ]; then core_exist=1; else core_exist=0; fi
    if [ -x "$CORE_PATH" ]; then core_exec=1; else core_exec=0; fi
    if [ -f /etc/config/webdav ]; then cfg_exist=1; else cfg_exist=0; fi
    enabled=$(uci -q get webdav.config.enabled) || enabled=0
    echo '{"running":'"$running"',"port":"'"$port"'","root":"'"$root_path"'","used":"'"$used"'","total":"'"$total"'","avail":"'"$avail"'","version":"'"$PKG_VERSION"'","core_exist":'"$core_exist"',"core_exec":'"$core_exec"',"cfg_exist":'"$cfg_exist"',"enabled":'"$enabled"'}'
}

get_version() {
    echo "$PKG_VERSION"
}

get_log() {
    logread -l 100 2>/dev/null | grep -i webdav || true
}

test_connection() {
    port=$(uci -q get webdav.config.port) || port=6065
    if curl -fsS -o /dev/null "http://127.0.0.1:$port/" 2>/dev/null; then
        echo '{"ok":true}'
    else
        echo '{"ok":false,"msg":"无法连接 127.0.0.1:'"$port"'"}'
    fi
}

case "$1" in
    get_arch)        get_arch ;;
    get_core_path)   echo "$CORE_PATH" ;;
    check_core)      [ -x "$CORE_PATH" ] ;;
    download_core)   download_core ;;
    prepare_config)  prepare_config ;;
    get_status)      get_status ;;
    get_version)     get_version ;;
    get_log)         get_log ;;
    test_connection) test_connection ;;
    *) echo "Usage: $0 {get_arch|get_core_path|check_core|download_core|prepare_config|get_status|get_version|get_log|test_connection}"; exit 1 ;;
esac
""",

    # ===================== LuCI 菜单 / rpcd 权限 =====================
    "root/usr/share/luci/menu.d/luci-app-webdav.json": """{
    "admin/services/webdav": {
        "title": "豆豉WebDAV",
        "order": 60,
        "action": { "type": "firstchild" }
    },
    "admin/services/webdav/dashboard": {
        "title": "运行状态",
        "order": 1,
        "action": { "type": "view", "path": "webdav/dashboard" }
    },
    "admin/services/webdav/settings": {
        "title": "服务设置",
        "order": 2,
        "action": { "type": "view", "path": "webdav/settings" }
    }
}
""",
    "root/usr/share/rpcd/acl.d/luci-app-webdav.json": """{
    "unauthenticated": {
        "description": "豆豉WebDAV helper access",
        "read": {
            "ubus": { "service": ["list"] }
        },
        "write": {
            "uci": [ "webdav" ],
            "ubus": { "service": [ "restart", "state", "list" ] },
            "file": {
                "/usr/share/webdav/helper.sh": [ "exec" ],
                "/sbin/logread": [ "exec" ],
                "/etc/init.d/webdav": [ "exec" ]
            }
        }
    }
}
""",

    # ===================== LuCI 视图（纯 JS，无 npm） =====================
    "root/www/luci-static/resources/view/webdav/settings.js": """'use strict';
'require view';
'require form';
'require fs';

return view.extend({
    render: function() {
        var m, s, o;
        m = new form.Map('webdav', _('豆豉WebDAV 设置'), _('配置豆豉WebDAV 文件共享服务（后端 hacdias/webdav）。'));
        this.map = m;

        s = m.section(form.TypedSection, 'webdav', _('常规设置'));
        s.anonymous = true;

        o = s.option(form.Flag, 'enabled', _('启用服务'));
        o.rmempty = false;

        o = s.option(form.Value, 'port', _('监听端口'));
        o.datatype = 'port';
        o.default = '6065';

        o = s.option(form.Value, 'root_path', _('共享根目录'), _('软路由上要共享的目录，如 /mnt/sata1'));
        o.rmempty = false;

        o = s.option(form.Value, 'username', _('用户名'));
        o = s.option(form.Value, 'password', _('密码'));
        o.password = true;

        o = s.option(form.Value, 'prefix', _('URL 前缀'), _('默认 /；如 /dav 则访问 http://路由器:端口/dav/'));
        o.default = '/';

        o = s.option(form.Flag, 'read_only', _('只读模式'));

        return m.render();
    },
    handleSave: function(ev) {
        var view = this;
        if (!view.map.validate()) return;
        return view.map.save().then(function() {
            return fs.exec('/etc/init.d/webdav', ['restart']);
        });
    },
    handleSaveApply: function(ev) {
        var view = this;
        if (!view.map.validate()) return;
        return view.map.save().then(function() {
            return fs.exec('/etc/init.d/webdav', ['restart']);
        });
    }
});
""",
    "root/www/luci-static/resources/view/webdav/dashboard.js": """'use strict';
'require view';
'require fs';
'require ui';

return view.extend({
    load: function() {
        var self = this;
        self._busy = false;
        return fs.exec('/usr/share/webdav/helper.sh', ['get_status'])
            .then(function(res) { self.status = JSON.parse(res.stdout || '{}'); return self.status; })
            .then(function() {
                return fs.exec('/usr/share/webdav/helper.sh', ['get_log']);
            })
            .then(function(res) {
                self.status.log = (res.stdout || '').trim();
                self.status.logOk = res.code === 0;
                return self.status;
            })
            .catch(function() { return { running: 0, log: '' }; });
    },
    render: function(data) {
        var view = this;
        var status = data.running ? '运行中 · 端口 ' + (data.port || '-') : '已停止';
        var diag = [];
        if (!data.running) {
            diag.push(E('h3', { 'style': 'color:#c00' }, _('诊断信息')));
            if (!data.core_exist) {
                diag.push(E('p', { 'style': 'color:#c00' }, _('⚠ 核心二进制不存在：/usr/bin/webdav-go 未找到。请先到「服务设置」中启用服务并保存，然后点击下方按钮下载并启动。')));
            } else if (!data.core_exec) {
                diag.push(E('p', { 'style': 'color:#c00' }, _('⚠ 核心二进制不可执行：请 chmod 0755 /usr/bin/webdav-go')));
            }
            if (!data.cfg_exist) {
                diag.push(E('p', { 'style': 'color:#c00' }, _('⚠ 配置文件缺失：/etc/config/webdav 不存在')));
            }
            if (data.enabled > 0 && !data.core_exist) {
                diag.push(E('div', { 'style': 'margin-top:10px' }, [
                    E('button', {
                        'class': 'cbi-button cbi-button-apply',
                        'disabled': view._busy,
                        'click': function() { view._downloadAndStart(); }
                    }, view._busy ? _('正在下载并启动...') : _('下载并启动服务'))
                ]));
            }
        }
        var children = [
            E('h2', { 'class': 'title' }, _('豆豉WebDAV 状态')),
            E('div', { 'class': 'cbi-section' }, [
                E('p', _('版本：') + (data.version || '-')),
                E('p', _('状态：') + status),
                E('p', _('共享目录：') + (data.root || '-')),
                E('p', _('磁盘用量：') + (data.used || '?') + ' / ' + (data.total || '?') + '（可用 ' + (data.avail || '?') + ')'),
                E('p', _('访问地址：http://') + location.hostname + ':' + (data.port || '6065'))
            ].concat(diag)),
            E('div', { 'class': 'cbi-section' }, [
                E('p', {}, _('提示：首次启用会自动按架构下载豆豉WebDAV 核心到 /usr/bin/webdav-go，请稍候。'))
            ])
        ];
        if (data.log) {
            children.push(E('div', { 'class': 'cbi-section' }, [
                E('h3', { 'style': 'color:#c00' }, _('运行日志')),
                E('pre', { 'style': 'background:#f5f5f5;padding:8px;overflow:auto;font-size:12px;white-space:pre-wrap;word-break:break-all' }, data.log)
            ]));
        }
        return E('div', { 'class': 'cbi-map' }, children);
    },
    _downloadAndStart: function() {
        var view = this;
        view._busy = true;
        view.render(view.status);
        ui.addNotification(null, E('p', {}, _('正在下载核心二进制，请稍候...')), 'info');
        fs.exec('/usr/share/webdav/helper.sh', ['download_core'])
            .then(function(res) {
                var result = JSON.parse(res.stdout || '{}');
                if (!result.ok) {
                    ui.addNotification(null, E('p', {}, _('下载失败：' + (result.msg || '请检查路由器网络') + '。你也可以手动下载二进制放到 /usr/bin/webdav-go')), 'error');
                    view._busy = false;
                    return;
                }
                ui.addNotification(null, E('p', {}, _('下载成功，正在启动服务...')), 'info');
                return fs.exec('/etc/init.d/webdav', ['start']);
            })
            .then(function() {
                window.location.reload();
            })
            .catch(function(err) {
                ui.addNotification(null, E('p', {}, _('操作失败，请检查 logread')), 'error');
                view._busy = false;
            });
    },
    handleSaveApply: null,
    handleSave: null,
    handleReset: null
});
""",
}


def create_source_tree(src_dir):
    """把 src_files 写到 src/，CONTROL/control 的 Version 动态替换为 PKG_VERSION。"""
    print(f"Creating source tree in '{src_dir}'...")
    if os.path.exists(src_dir):
        shutil.rmtree(src_dir)
    for rel_path, content in src_files.items():
        full_path = os.path.join(src_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        if rel_path == "CONTROL/control":
            content = re.sub(r'Version:\s*.*', f'Version: {PKG_VERSION}', content)
        content = content.replace('__PKG_VERSION__', PKG_VERSION)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        # 脚本类文件本地置可执行（与 make_tar_gz 对称）
        if ("CONTROL/" in rel_path and rel_path != "CONTROL/control") or "etc/init.d/" in rel_path or "usr/share/webdav/helper.sh" in rel_path:
            os.chmod(full_path, 0o755)
    print("Source tree created successfully.")


def make_tar_gz(source_dir, output_filename, is_control=False):
    """可复现打包：root:root、固定 mtime、'./' 前缀、正确权限。"""
    print(f"Archiving '{source_dir}' -> '{output_filename}'...")
    with tarfile.open(output_filename, "w:gz") as tar:
        all_entries = []
        for root, dirs, files in os.walk(source_dir):
            for d in dirs:
                full_path = os.path.join(root, d)
                all_entries.append((os.path.relpath(full_path, source_dir), full_path, True))
            for f in files:
                full_path = os.path.join(root, f)
                all_entries.append((os.path.relpath(full_path, source_dir), full_path, False))
        all_entries.sort(key=lambda x: x[0])

        root_ti = tarfile.TarInfo(name=".")
        root_ti.type = tarfile.DIRTYPE
        root_ti.mode = 0o755
        root_ti.uid = root_ti.gid = 0
        root_ti.uname = root_ti.gname = "root"
        root_ti.mtime = 1700000000
        tar.addfile(root_ti)

        for rel_path, full_path, is_dir in all_entries:
            ti = tar.gettarinfo(full_path, arcname="./" + rel_path)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mtime = 1700000000
            if is_dir:
                ti.type = tarfile.DIRTYPE
                ti.mode = 0o755
                tar.addfile(ti)
            else:
                ti.type = tarfile.REGTYPE
                if is_control:
                    ti.mode = 0o755 if os.path.basename(full_path) in ["postinst", "postrm", "preinst", "prerm"] else 0o644
                else:
                    ti.mode = 0o755 if ("etc/init.d/" in rel_path or "usr/share/webdav/helper.sh" in rel_path) else 0o644
                with open(full_path, "rb") as f:
                    tar.addfile(ti, f)


def write_tar_gz_outer_archive(archive_path, file_list):
    """最终 .ipk = gzip tar，含 debian-binary / control.tar.gz / data.tar.gz。"""
    print(f"Creating IPK archive '{archive_path}'...")
    with tarfile.open(archive_path, "w:gz") as tar:
        for name, data in file_list:
            ti = tarfile.TarInfo(name="./" + name)
            ti.size = len(data)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            ti.mtime = 1700000000
            ti.mode = 0o644
            ti.type = tarfile.REGTYPE
            tar.addfile(ti, io.BytesIO(data))


def increment_version():
    """自增 PKG_VERSION（原地改写本脚本），更新内存变量。"""
    global PKG_VERSION, IPK_FILENAME
    with open(__file__, "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r'PKG_VERSION\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        print("Warning: PKG_VERSION not found.")
        return
    current = match.group(1)
    if '-' in current:
        ver, rev = current.rsplit('-', 1)
        try:
            new_ver = f"{ver}-{int(rev) + 1}"
        except ValueError:
            new_ver = current + ".1"
    else:
        parts = current.split('.')
        try:
            parts[-1] = str(int(parts[-1]) + 1)
            new_ver = '.'.join(parts)
        except ValueError:
            new_ver = current + "-1"
    content = re.sub(r'PKG_VERSION\s*=\s*["\']([^"\']+)["\']', f'PKG_VERSION = "{new_ver}"', content, count=1)
    with open(__file__, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Incremented version: {current} -> {new_ver}")
    PKG_VERSION = new_ver
    IPK_FILENAME = f"{PKG_NAME}_{PKG_VERSION}_{PKG_ARCH}.ipk"


def main():
    increment_version()
    workspace = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(workspace, "src")
    build_dir = os.path.join(workspace, "build")
    dist_dir = os.path.join(workspace, "dist")
    print("Initializing source tree for luci-app-webdav...")
    create_source_tree(src_dir)
    if os.path.exists(build_dir):
        shutil.rmtree(build_dir)
    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(dist_dir, exist_ok=True)
    control_tar = os.path.join(build_dir, "control.tar.gz")
    data_tar = os.path.join(build_dir, "data.tar.gz")
    make_tar_gz(os.path.join(src_dir, "CONTROL"), control_tar, is_control=True)
    make_tar_gz(os.path.join(src_dir, "root"), data_tar, is_control=False)
    with open(control_tar, "rb") as f:
        control_bytes = f.read()
    with open(data_tar, "rb") as f:
        data_bytes = f.read()
    file_list = [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control_bytes),
        ("data.tar.gz", data_bytes),
    ]
    ipk_path = os.path.join(dist_dir, IPK_FILENAME)
    write_tar_gz_outer_archive(ipk_path, file_list)
    print("\nSUCCESS!")
    print(f"Packaged IPK file created at: {ipk_path}")


if __name__ == "__main__":
    main()
