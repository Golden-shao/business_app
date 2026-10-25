#!/usr/bin/env bash
# Small Amazon Linux 2023 preview host; does not provision or resize AWS resources.
set -euo pipefail
umask 077
domain=${1:?Usage: sudo bash install.sh DOMAIN REVIEWED_COMMIT}
commit=${2:?Provide a reviewed 40-character Git commit}
mode=${3:-private}
[[ $EUID == 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ $domain =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ && $domain == *.* ]] || exit 1
[[ $commit =~ ^[a-f0-9]{40}$ ]] || exit 1
[[ $mode == private || $mode == public-demo ]] || exit 1
source /etc/os-release
[[ $ID == amzn && $VERSION_ID == 2023 ]] || { echo 'Requires Amazon Linux 2023.' >&2; exit 1; }

dnf install -y python3.12 python3.12-pip valkey git tar gzip
# AL2023 ships curl-minimal; installing full curl alongside it conflicts.
command -v curl >/dev/null || dnf install -y curl-minimal
id modeljetty >/dev/null 2>&1 || useradd --system --home-dir /var/lib/modeljetty --shell /sbin/nologin modeljetty
id caddy >/dev/null 2>&1 || useradd --system --home-dir /var/lib/caddy --shell /sbin/nologin caddy
install -d -m 755 /opt/modeljetty/releases /etc/modeljetty /var/lib/modeljetty
install -d -m 700 -o valkey -g valkey /var/lib/modeljetty/redis
install -d -m 700 -o caddy -g caddy /var/lib/caddy

release=/opt/modeljetty/releases/$commit
if [[ ! -d $release/.git ]]; then
  git init "$release"
  git -C "$release" remote add origin https://github.com/Golden-shao/modeljetty.git
  git -C "$release" fetch --depth 1 origin "$commit"
  git -C "$release" checkout --detach FETCH_HEAD
fi
[[ $(git -C "$release" rev-parse HEAD) == "$commit" ]]
python3.12 -m venv "$release/.venv"
"$release/.venv/bin/pip" install --no-cache-dir -r "$release/gateway/requirements.txt"
# Runtime users can read code, but cannot edit the installed release.
chmod -R go+rX "$release"

python3.12 - "$mode" <<'PY'
import os
from pathlib import Path
import secrets
import sys
p = Path('/etc/modeljetty/gateway.env')
if not p.exists():
    with open(p, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as f:
        f.write('ADMIN_TOKEN=' + secrets.token_urlsafe(32) + '\n')
        f.write('GATEWAY_TOKEN=' + secrets.token_urlsafe(32) + '\n')
        f.write('REDIS_URL=redis://127.0.0.1:6379/0\nPROVIDER=mock\n')
        f.write('RATE_LIMIT_PER_MINUTE=30\nCACHE_TTL_SECONDS=0\nCORS_ORIGINS=[]\n')
lines = p.read_text().splitlines()
values = dict(line.split('=', 1) for line in lines if '=' in line)
enabled = sys.argv[1] == 'public-demo'
if enabled and values.get('PROVIDER', 'mock') != 'mock':
    raise SystemExit('Public demo cannot be enabled with a real provider')
p.write_text('\n'.join(line for line in lines if not line.startswith('PUBLIC_DEMO_ENABLED='))
             + '\nPUBLIC_DEMO_ENABLED=' + str(enabled).lower() + '\n')
p.chmod(0o600)
PY

cat > /etc/modeljetty/valkey.conf <<'EOF'
bind 127.0.0.1
protected-mode yes
port 6379
daemonize no
dir /var/lib/modeljetty/redis
appendonly yes
appendfsync everysec
save ""
maxmemory 96mb
maxmemory-policy noeviction
EOF
chmod 644 /etc/modeljetty/valkey.conf
cat > /etc/systemd/system/modeljetty-redis.service <<'EOF'
[Unit]
Description=ModelJetty Redis-compatible Valkey store
After=network.target
[Service]
User=valkey
Group=valkey
ExecStart=/usr/bin/valkey-server /etc/modeljetty/valkey.conf
Restart=on-failure
RestartSec=3
MemoryMax=192M
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/modeljetty/redis
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/modeljetty-gateway.service <<EOF
[Unit]
Description=ModelJetty gateway ($commit)
After=network-online.target modeljetty-redis.service
Wants=network-online.target modeljetty-redis.service
[Service]
User=modeljetty
Group=modeljetty
WorkingDirectory=$release/gateway
EnvironmentFile=/etc/modeljetty/gateway.env
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=$release/.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=3
MemoryMax=256M
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
[Install]
WantedBy=multi-user.target
EOF

# Pin the upstream binary and verify it against the release's SHA512 manifest.
caddy_version=2.11.7
tmp=$(mktemp -d)
trap 'rm -f "$tmp/caddy.tar.gz" "$tmp/checksums.txt" "$tmp/caddy"; rmdir "$tmp" 2>/dev/null || true' EXIT
base=https://github.com/caddyserver/caddy/releases/download/v$caddy_version
curl --fail --location "$base/caddy_${caddy_version}_linux_amd64.tar.gz" -o "$tmp/caddy.tar.gz"
curl --fail --location "$base/caddy_${caddy_version}_checksums.txt" -o "$tmp/checksums.txt"
expected=$(awk -v file="caddy_${caddy_version}_linux_amd64.tar.gz" '$2 == file {print $1}' "$tmp/checksums.txt")
[[ $expected =~ ^[a-f0-9]{128}$ ]]
printf '%s  %s\n' "$expected" "$tmp/caddy.tar.gz" | sha512sum --check
tar -xzf "$tmp/caddy.tar.gz" -C "$tmp" caddy
install -m 755 "$tmp/caddy" /usr/local/bin/caddy
cat > /etc/modeljetty/Caddyfile <<EOF
$domain {
  encode zstd gzip
  request_body {
    max_size 64KB
  }
  header {
    X-Content-Type-Options nosniff
    Referrer-Policy same-origin
    X-Frame-Options DENY
  }
  reverse_proxy 127.0.0.1:8000
}
EOF
chmod 644 /etc/modeljetty/Caddyfile
cat > /etc/systemd/system/modeljetty-web.service <<'EOF'
[Unit]
Description=ModelJetty public HTTPS entrypoint
After=network-online.target modeljetty-gateway.service
Wants=network-online.target modeljetty-gateway.service
[Service]
User=caddy
Group=caddy
Environment=HOME=/var/lib/caddy
ExecStart=/usr/local/bin/caddy run --config /etc/modeljetty/Caddyfile --adapter caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/modeljetty/Caddyfile --adapter caddyfile
Restart=on-failure
RestartSec=3
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
MemoryMax=128M
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/caddy
[Install]
WantedBy=multi-user.target
EOF
systemd-analyze verify /etc/systemd/system/modeljetty-{redis,gateway,web}.service
/usr/local/bin/caddy validate --config /etc/modeljetty/Caddyfile --adapter caddyfile
systemctl daemon-reload
systemctl enable modeljetty-redis modeljetty-gateway modeljetty-web
systemctl restart modeljetty-redis modeljetty-gateway modeljetty-web
curl --fail --retry 15 --retry-delay 2 --retry-connrefused http://127.0.0.1:8000/health/ready
echo
echo "Configured https://$domain; verify its public certificate and authenticated requests before sharing."
echo 'Credentials remain in root-only /etc/modeljetty/gateway.env. No Kubernetes or paid model is configured.'
