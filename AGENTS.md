# 豆豉WebDAV — OpenWrt LuCI app for hacdias/webdav

## Source of truth

All deliverable files live in `src_files` dict inside `build_ipk.py` — **edit there**, not in `src/`. `src/` is a build artifact (in `.gitignore`), regenerated every build.

## Build & deploy

```sh
python3 build_ipk.py          # auto-increments version, regenerate src/ → dist/*.ipk
                              # ⚠️ opkg refuses downgrade — if router has X.Y.Z, new version must be higher
./deploy.sh                   # scp + ssh to router, expects expect + password edit
```

`deploy.sh` requires editing `PASSWORD` + `ROUTER_IP` (default: `192.168.66.1`). Uses `expect` for password auth.

## Architecture

- **Init**: `root/etc/init.d/webdav` — procd-based, `START=95`. Reads UCI config, downloads Go binary on first run if missing.
- **Backend**: `root/usr/share/webdav/helper.sh` — case-dispatch shell script (`get_arch|get_core_path|check_core|download_core|prepare_config|get_status|test_connection`). Produces `/tmp/webdav_run.yaml` for the Go binary.
- **Core**: `hacdias/webdav` Go binary (`CORE_VERSION=v5.4.0`), auto-downloaded per arch (`webdav-linux-$arch`), installed to `/usr/bin/webdav-go`.
- **UCI config**: `/etc/config/webdav` — options: `enabled`, `port` (default 6065), `root_path` (default /mnt/sata1), `username`, `password`, `read_only`, `prefix`.
- **LuCI views**: plain JS (no npm), LuCI `form.Map` + `fs.exec` patterns — pure client-side, calls `helper.sh` via ubus/rpcd.
- **ACL**: `root/usr/share/rpcd/acl.d/luci-app-webdav.json` — unauthenticated access to uci + helper.sh exec + logread.

## Key conventions

- JSON in shell scripts: single-quote outer, double-quote inner literals, variable concatenation — avoids double-escape issues (see `helper.sh`).
- Binary permissions: 0755 for init.d scripts, helper.sh, and CONTROL scripts. 0644 for everything else.
- Reproducible tar: `root:root`, fixed mtime `1700000000`, `./` prefix in tar entries.
