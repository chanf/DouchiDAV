# 水杉WebDAV

iStoreOS / OpenWrt 上的 **水杉WebDAV 文件共享 LuCI 应用**。后端采用 [hacdias/webdav](https://github.com/hacdias/webdav)（Go 单二进制），前端为 LuCI 配置页 + 运行状态页，服务由 procd 守护、崩溃自动重启。核心二进制按 CPU 架构首次启用时从 GitHub 下载，包本体只含脚本/配置/JS，因此体积小、`Architecture: all`、可随时升级核心。

> 本项目骨架（构建系统 + CONTROL + 部署脚本）移植自 `luci-app-mihomo`，仅替换业务层。维护者如已熟悉 mihomo，可快速上手——详见文末「与 luci-app-mihomo 的关系」。

---

## 一、为什么有这个项目（背景）

软路由（iStoreOS）上常见的内置 WebDAV（如某些固件自带的 go-webdav）存在**请求体大小硬限制**（实测 4MB：超过 4MB 的 PUT 会在 4MB 处被截断并返回 HTTP 405），导致大文件无法上传。本插件用规范的 `hacdias/webdav` 替换之，**无此限制**，并配 LuCI 界面方便配置。

适用场景：把软路由上挂载的硬盘（如 `/mnt/sata1`）通过 WebDAV 共享给局域网内的播放器、笔记客户端（如 Rong VideoPlayer 的「网络空间」）等直接读写。

---

## 二、功能特性

- **LuCI Web 界面**配置：启用开关、监听端口、共享根目录、用户名/密码、URL 前缀、只读模式
- **procd 守护**：服务进程崩溃自动 respawn；UCI 配置变更自动 reload
- **按需下载核心**：首次启用时按 `uname -m` 探测架构，从 GitHub Releases 下载对应的 `webdav-linux-<arch>` 到 `/usr/bin/webdav-go`，无需把二进制打进包里
- **运行状态页**：进程是否存活、监听端口、共享根目录磁盘用量、访问地址
- **UCI 配置保护**：升级（opkg 覆盖安装）时用户已改的设置不丢失（`conffiles` 登记）
- **可复现构建**：同一份 `src_files` 产出 byte 一致的 `.ipk`（固定 uid/gid/mtime/权限）

---

## 三、架构设计

整体是「LuCI 配置 → init.d 编排 → 后台守护进程 + helper.sh 后端 → 前端 JS 调 rpcd」的经典 OpenWrt LuCI 应用结构。

```
用户在 LuCI 改配置（UCI）
        │  保存并应用
        ▼
/etc/init.d/webdav (procd)
        │  1) 确保 /usr/bin/webdav-go 存在（缺失则 helper.sh download_core）
        │  2) helper.sh prepare_config 生成 /tmp/webdav_run.yaml
        │  3) procd 拉起 webdav-go -c /tmp/webdav_run.yaml（respawn）
        ▼
hacdias/webdav 进程（监听端口，提供 WebDAV 服务）
        ▲
        │  fs.exec('/usr/share/webdav/helper.sh', ['get_status'])
LuCI dashboard.js ──rpcd──▶ helper.sh get_status 返回 JSON（进程/端口/磁盘）
```

**三个核心概念（务必理解）：**

1. **单源真相 `src_files`**：打进 `.ipk` 的所有文件，都是 `build_ipk.py` 顶部 `src_files` 字典里的字符串值。`src/`、`build/`、`dist/` 全部由构建「先删后建」生成，是纯产物。**改任何交付文件 = 改 `src_files` 里对应字符串，然后重新构建**；切勿手编 `src/`。
2. **procd 编排**：`/etc/init.d/webdav` 用 `USE_PROCD=1` + `procd_set_param respawn` 守护 webdav 进程；`service_triggers` + `procd_add_reload_trigger "webdav"` 让 LuCI「保存并应用」自动重启服务。
3. **UCI 是真相，磁盘配置只是运行态**：用户配置存 `/etc/config/webdav`（UCI）；`helper.sh prepare_config` 把 UCI 选项拼成 `/tmp/webdav_run.yaml`（RAM，重启清空），进程读它启动。不要让进程直接读 UCI。

---

## 四、目录结构

### 本仓库（源）

```
luci-app-sswebdav/
├── build_ipk.py        # 单源真相：src_files + 四个打包函数 + main。改文件改这里
├── deploy.sh           # 自动部署：scp 上传 ipk → opkg install → 重启 webdav
├── .gitignore          # 忽略 build/ dist/ src/（纯产物）
├── README.md           # 本文件
├── src/                # [构建产物] create_source_tree 写盘，勿手编
├── build/              # [构建产物] control.tar.gz / data.tar.gz 中间产物
└── dist/               # [构建产物] 最终 .ipk
```

### 打进 .ipk 的文件（即 `src_files` 的 key）

```
CONTROL/
├── control             # 包元数据（Package/Version/Depends/Architecture）
├── postinst            # 安装后：清 LuCI 缓存、重启 rpcd
├── postrm              # 卸载后：清缓存、重启 rpcd
└── conffiles           # 升级时保留的配置（/etc/config/webdav）—— 最重要

root/
├── etc/config/webdav                         # UCI 默认配置
├── etc/init.d/webdav                         # procd 守护脚本
├── usr/share/webdav/helper.sh                # 单体后端（case 分发 7 子命令）
├── usr/share/luci/menu.d/luci-app-sswebdav.json    # LuCI 菜单注册
├── usr/share/rpcd/acl.d/luci-app-sswebdav.json     # rpcd 权限授予（前端调 helper.sh 的依据）
└── www/luci-static/resources/view/webdav/
    ├── settings.js                           # 设置页（UCI 表单）
    └── dashboard.js                          # 状态页（调 helper.sh get_status）
```

---

## 五、快速开始（构建 + 部署）

```bash
python3 build_ipk.py     # 产出 dist/luci-app-sswebdav_<ver>_all.ipk（每次自增版本号）
# 改 deploy.sh 里 PASSWORD，然后：
./deploy.sh              # scp 上传 + opkg install + /etc/init.d/webdav restart
```

或手动部署：
```bash
scp dist/luci-app-sswebdav_*.ipk root@路由器IP:/tmp/
ssh root@路由器IP "opkg install /tmp/luci-app-sswebdav_*.ipk && /etc/init.d/webdav restart"
```

装好后：LuCI → 服务 → **水杉WebDAV** → 服务设置 → 启用、配端口/根目录/账号密码 → 保存并应用（首次启用会按架构下载核心，用 `logread` 看进度）。访问 `http://路由器IP:端口/`。

> 依赖：仅 `luci-base` + `curl`（下载核心/调 API 用）。无需 nftables/kmod。

---

## 六、开发流程（日常改动）

改任何交付文件的标准流程：

1. 改 `build_ipk.py` 里 `src_files` 字典对应 key 的字符串值（**切勿手编 `src/`，下次构建会被覆盖**）
2. `python3 build_ipk.py`（自增版本号 → 写盘 src/ → 打包）
3. `./deploy.sh`（部署到路由器）
4. 在路由器 LuCI 验证

> **基本规则**：每次构建新版本后，务必部署并安装到软路由，确保远程测试环境与本地代码同步。

---

## 七、逐文件详解

### CONTROL/control（包元数据）
- `Version` 写死占位，构建时由 `create_source_tree` 正则替换成当前 `PKG_VERSION`。**版本号真正来源是 `build_ipk.py` 顶部的 `PKG_VERSION`**，别去改 control 里的。
- `Depends: luci-base, curl`：WebDAV 不需要 nftables/kmod。
- `Architecture: all`：核心二进制运行时按架构下载，包本身与架构无关。

### CONTROL/conffiles（**最重要**）
登记 `/etc/config/webdav`。**升级（opkg 覆盖安装）时用户已改的配置不被包默认值覆盖**。漏掉这一行会导致每次升级用户配置归零——mihomo 曾因此覆盖过用户的订阅地址，血泪教训。

### root/etc/config/webdav（UCI 默认配置）
段名 `config`、类型 `webdav`，与 init.d / helper.sh 里的 `uci -q get webdav.config.<key>` 一一对应。`enabled` 默认 `0`（装上不自动开服务，避免没设密码就暴露目录）。详见「UCI 配置项」一节。

### root/etc/init.d/webdav（procd 守护）
`USE_PROCD=1` 必须有，否则走老式 SysV init、`procd_*` 调用无效。流程：读 UCI → 确保核心二进制存在（缺失则 `download_core`）→ `mkdir -p` 根目录 → `prepare_config` 生成 `/tmp/webdav_run.yaml` → `procd_open_instance` 拉起进程（`procd_set_param respawn` 崩溃自动重启）。`service_triggers` + `procd_add_reload_trigger "webdav"` 让 LuCI「保存并应用」自动 reload 服务。

### root/usr/share/webdav/helper.sh（单体后端）
`case "$1"` 分发 7 个子命令：

| 子命令 | 作用 |
|--------|------|
| `get_arch` | 探测 CPU 架构（amd64/arm64/arm/mips/mipsle） |
| `get_core_path` | 返回核心路径 `/usr/bin/webdav-go` |
| `check_core` | 二进制是否存在且可执行 |
| `download_core` | 按架构从 GitHub 下载核心（curl） |
| `prepare_config` | 用 UCI 选项拼 `/tmp/webdav_run.yaml` |
| `get_status` | 进程存活 + 端口 + 根目录磁盘用量，返回 JSON |
| `test_connection` | curl 自测端口是否通 |

配置读取用 `uci -q get webdav.config.xxx`（**无需 source 任何库**，比 init.d 的 `config_load` 更省事）。**JSON 输出统一用「单引号包裹 + 内部双引号字面量 + 变量拼接」**，如 `echo '{"ok":true,"path":"'"$CORE_PATH"'"}'`——避开 shell / Python 双重转义，详见「关键约定」。

### LuCI 菜单与 rpcd 权限（两个 JSON）
- `menu.d/luci-app-sswebdav.json`：注册「服务 → 水杉WebDAV」菜单 + 两个子页（4 空格缩进）。
- `acl.d/luci-app-sswebdav.json`：**rpcd 权限授予**，是前端 JS 能调 helper.sh / init.d / logread 的依据（Tab 缩进）。漏写会导致前端 `fs.exec` 被拦截报权限错误。

### settings.js / dashboard.js（纯 JS 视图）
无 npm、无编译。`settings.js` 用 `form.Map('webdav')` + `m.restart = 'webdav'`（保存后重启服务）。`dashboard.js` 用 `fs.exec('/usr/share/webdav/helper.sh', ['get_status'])` 拿 JSON 渲染状态。

---

## 八、构建系统（build_ipk.py）

`build_ipk.py` 由三部分组成：①顶部常量 + `src_files` 字典；②四个打包函数；③`main` 流程。

`.ipk` 本质是一个 **gzip tar 包**，含三个成员：
- `debian-binary`（内容固定 `2.0\n`，声明 ipk 格式版本）
- `control.tar.gz`（由 `src/CONTROL/` 打包：control + postinst + postrm + conffiles）
- `data.tar.gz`（由 `src/root/` 打包：所有交付到文件系统的文件）

`main` 流程：`increment_version` → `create_source_tree`（写 `src/`）→ 重建 `build/` `dist/` → `make_tar_gz`（分别打 CONTROL / root）→ `write_tar_gz_outer_archive`（三成员组装成最外层 `.ipk`）。

**四个函数要点（移植自 mihomo，勿随意改）：**

| 函数 | 职责 |
|------|------|
| `create_source_tree` | 把 `src_files` 写到 `src/`；把 `CONTROL/control` 的 `Version:` 正则替换成当前 `PKG_VERSION`；脚本类文件（postinst/postrm/init.d/helper.sh）本地置 `0o755` |
| `make_tar_gz` | **可复现打包**——强制 uid/gid=0、uname/gname=root、mtime=1700000000、`./` 前缀；脚本类 `0o755`，其余 `0o644`。同一输入产出 byte 一致的 ipk 全靠这组固定元数据 |
| `write_tar_gz_outer_archive` | 把三个成员压成最外层 `.ipk`（同样是 gzip tar + 固定元数据） |
| `increment_version` | 正则定位 `PKG_VERSION`，自增（`1.0.0-2` → `1.0.0-3`），**原地改写本脚本**。⚠️ 每次构建都会自改 `build_ipk.py`，产生 diff 属预期；**勿重命名 `PKG_VERSION` 变量**，否则自增正则失配 |

仅依赖 Python 3 标准库（`os, tarfile, io, shutil, re`），无需虚拟环境或第三方包。

---

## 九、UCI 配置项

| 选项 | 默认 | 说明 |
|------|------|------|
| `enabled` | `0` | 启用服务 |
| `port` | `6065` | 监听端口 |
| `root_path` | `/mnt/sata1` | 共享根目录 |
| `username` | `admin` | 用户名 |
| `password` | （空） | 密码（明文存 UCI，MVP 取舍；软路由本地配置权限受限于 root） |
| `read_only` | `0` | 只读模式（1=R，0=CRUD） |
| `prefix` | `/` | URL 前缀（如 `/dav` 则访问 `http://路由器:端口/dav/`） |

命令行改配置：`uci set webdav.config.port=8080; uci commit webdav; /etc/init.d/webdav restart`。

---

## 十、后端核心二进制（hacdias/webdav）

- **版本**：`helper.sh` 的 `CORE_VERSION`（当前 `v5.4.0`，以 [GitHub Releases](https://github.com/hacdias/webdav/releases) 实际为准；改后重新构建）。
- **架构映射**：`get_arch()` 把 `uname -m` 映射到 hacdias/webdav 的 release 命名（x86_64→amd64、aarch64→arm64、armv7l→armv7、armv6l→armv6、mips→mips、mipsel→mipsle）。⚠️ mips 大/小端视固件而定，可能要调整。
- **自动下载**：首次启用服务时，`init.d/webdav` 自动调用 `helper.sh download_core`，从 GitHub Releases 下载 `linux-$arch-webdav.tar.gz` 并解压到 `/usr/bin/webdav-go`。
- **配置**：`prepare_config` 生成 YAML（`address`/`prefix`/`directory`/`permissions`/`users`）。
- **替换后端**：若改用 `rclone serve webdav`，只需把 `prepare_config` 换成拼 rclone 命令行参数，其余骨架不变。

### 手动下载安装

若路由器无法访问 GitHub 或自动下载失败，在路由器终端执行：

```bash
# 先确认架构（J4125/N100 等 x86 路由器用 amd64）
uname -m
# 根据输出选择：
#   x86_64   → amd64
#   aarch64  → arm64
#   armv7l   → armv7
#   armv6l   → armv6

# 以 amd64 为例下载并安装（替换架构名称）：
arch=amd64
cd /tmp
curl -fL "https://github.com/hacdias/webdav/releases/download/v5.4.0/linux-$arch-webdav.tar.gz" -o wd.tar.gz
tar -xzf wd.tar.gz
cp webdav /usr/bin/webdav-go
chmod 0755 /usr/bin/webdav-go
rm -f wd.tar.gz webdav LICENSE README.md
/etc/init.d/webdav start
```

---

## 十一、关键约定与踩坑（务必遵守）

这些是用血泪换来的规则，新增/修改时逐条对照：

1. **单源真相**：改 `src_files`，勿手编 `src/`（会被覆盖）。
2. **shell JSON 引号**：helper.sh 用「单引号 + 双引号字面量 + 变量拼接」，勿用 `\"` 转义——历史教训：mihomo 曾因 `echo` 引号未转义导致整个 helper.sh 在路由器上 syntax error 无法加载。
3. **`conffiles` 必须登记** `/etc/config/webdav`，否则升级覆盖用户配置。
4. **rpcd ACL 必须显式授权** helper.sh / init.d / logread 的 `exec`，否则前端 `fs.exec` 被拦截。
5. **脚本可执行位两处对称**：`create_source_tree`（本地写盘）+ `make_tar_gz`（打包）都要给 `0o755`，缺一不可（缺则脚本在路由器上无执行权限、服务起不来）。**新增脚本类文件时，两处对称的 `if` 判断都要加上它**。
6. **版本号只认 `PKG_VERSION`**：`CONTROL/control` 里的 `Version` 是占位；勿重命名 `PKG_VERSION` 变量。
7. **两个 JSON 缩进不一致**：`menu.d/*.json` 4 空格、`acl.d/*.json` Tab，各自保留。
8. **批量操作走后端、勿前端并发**：状态/磁盘/端口合并到一个 `get_status` 一次性返回，前端只轮一个调用（避免每项一个 fs.exec 把 rpcd file-exec 打满超时）。

---

## 十二、排错

| 现象 | 排查 |
|------|------|
| LuCI 看不到「水杉WebDAV」菜单 | postinst 没清缓存/重启 rpcd → 手动 `/etc/init.d/rpcd restart`；或 `menu.d` JSON 路径/视图 path 不对应 |
| 服务起不来 | `logread` 看日志；`ls -l /usr/bin/webdav-go` 看核心是否下载成功；`ls -l /usr/share/webdav/helper.sh` 看是否可执行 |
| 前端调 helper.sh 报权限错误 | `acl.d` JSON 漏授权 → 检查 `/usr/share/rpcd/acl.d/luci-app-sswebdav.json` 是否含 helper.sh/init.d/logread 的 exec |
| 核心下载失败 | 路由器能否访问 GitHub；或手动下二进制放到 `/usr/bin/webdav-go` + `chmod 0755` |
| 大文件仍上传失败 | 确认客户端连的是本插件端口（默认 **6065**），不是旧的 go-webdav 端口（如 6086） |
| 升级后用户配置丢失 | `conffiles` 漏登记 → 检查 `CONTROL/conffiles` 是否含 `/etc/config/webdav` |
| 改了 src_files 但路由器上没变 | 忘了重新 `python3 build_ipk.py && ./deploy.sh`；或部署的是旧 ipk |

---

## 十三、路线图 / 可扩展

- **TLS**：UCI 的 `tls_cert`/`tls_key` 已预留，`prepare_config` 加 scheme + cert 即可
- **多用户**：YAML `users` 数组配置多项
- **共享多个目录**：多 procd 实例（参照 mihomo 的 3 实例写法）
- **上传/下载限速、流量统计**：core 层支持或加 nginx 前置
- **切换 rclone 后端**：支持本地 + 对象存储多后端，把 `prepare_config` 换成拼 rclone 命令行
- **架构自动适配 mips 大小端**：`get_arch` 用更可靠的探测（如读 `/proc/cpuinfo`）

---

## 十四、与 luci-app-mihomo 的关系

骨架（`build_ipk.py` 四函数 + CONTROL 模板 + `deploy.sh`）一字照搬自 `luci-app-mihomo`，仅替换业务层。维护者若熟悉 mihomo，按下表平移即可：

| mihomo | webdav | 说明 |
|--------|--------|------|
| `PKG_NAME = "luci-app-mihomo"` | `"luci-app-sswebdav"` | 顶部常量 |
| `/etc/config/mihomo` | `/etc/config/webdav` | UCI 配置 |
| `/etc/init.d/mihomo` | `/etc/init.d/webdav` | procd 脚本 |
| `/usr/share/mihomo/helper.sh` | `/usr/share/webdav/helper.sh` | 后端（注意 `make_tar_gz` 里的路径判断也要改） |
| 3 个 procd 实例 | 1 个实例 | 简化 |
| helper.sh ~20 子命令 | 7 子命令 | 见第七节 |
| 4 视图 | 2 视图（dashboard/settings） | MVP |
| `Depends: ..., kmod-nft-tproxy, curl` | `luci-base, curl` | 无需 nftables |
| `download_core` 下 mihomo | 下 webdav | 换 URL/版本 |
| `prepare_config` 拼 mihomo YAML | 拼 webdav YAML | 换模板 |

> 一句话：骨架不动、只换业务层——这就是把 mihomo 经验复用到 WebDAV 的全部秘诀。

---

## 十五、发布前检查清单

- [ ] `src_files` 里改对了（不是手编 `src/`）
- [ ] `CONTROL/control` 的 `Depends` 精简、`Architecture: all`
- [ ] `CONTROL/conffiles` 含 `/etc/config/webdav`
- [ ] `init.d/webdav` 有 `USE_PROCD=1`、`procd_set_param respawn`、`service_triggers`
- [ ] `helper.sh` 所有 JSON 输出用单引号拼接（无 `\"` 转义）
- [ ] 新增脚本类文件在 `create_source_tree` + `make_tar_gz` 两处都给了 `0o755`
- [ ] `menu.d` JSON 的 `path` 与视图文件路径对应（`path: webdav/xxx` ↔ `view/webdav/xxx.js`）
- [ ] `acl.d` JSON 授权了 helper.sh / init.d / logread 的 exec
- [ ] `PKG_NAME = "luci-app-sswebdav"`，`PKG_VERSION` 自增正常，**勿重命名该变量**
- [ ] `.gitignore` 忽略 `build/` `dist/` `src/`
- [ ] `python3 build_ipk.py` 成功产出 `dist/*.ipk`
- [ ] `./deploy.sh` 安装到软路由，LuCI 能看到「水杉WebDAV」菜单、启停正常、大文件可上传

---

## 许可

- 后端核心：[hacdias/webdav](https://github.com/hacdias/webdav)（MIT License © Henrique Dias）
- 本 LuCI 应用（配置页 / init 脚本 / helper）：随项目分发，按需开源
