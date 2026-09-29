#!/usr/bin/env bash
# Install an exact reviewed revision on a fresh Ubuntu VM. Nothing is started here:
# data migration and the existing tunnel's cutover must happen before activation.
set -euo pipefail
umask 077

die() { printf '%s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die 'Run this installer with sudo on the destination VM.'
[[ $# -eq 1 && $1 =~ ^[0-9a-f]{40}$ ]] || die 'Supply one full reviewed Git commit SHA.'
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || die 'This installer supports Ubuntu 24.04 only.'
[[ $(uname -m) == x86_64 ]] || die 'This installer supports x86_64 only.'

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
repo_git() { GIT_OPTIONAL_LOCKS=0 git -c safe.directory="$source_dir" -C "$source_dir" "$@"; }
[[ $(repo_git rev-parse HEAD) == "$1" ]] || die 'The checkout does not match the reviewed revision.'
[[ -z $(repo_git status --porcelain) ]] || die 'Use a clean committed checkout.'
for target in /opt/career-search /opt/openai-tunnel /etc/career-search; do
    [[ ! -e $target ]] || die "Existing installation at $target: review it before any upgrade."
done
for service_user in career-search career-tunnel; do
    ! id "$service_user" &>/dev/null || die "Existing user $service_user: review before installing."
done

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3-venv ca-certificates curl unzip

# Executable code remains root-owned; service users can write only their state directories.
for service_user in career-search career-tunnel; do
    useradd --system --user-group --home-dir "/var/lib/$service_user" \
        --shell /usr/sbin/nologin "$service_user"
    install -d -m 0700 -o "$service_user" -g "$service_user" "/var/lib/$service_user"
done
install -d -m 0755 /opt/career-search /opt/career-search/app /opt/openai-tunnel
install -d -m 0700 /etc/career-search
repo_git archive HEAD | tar -x -C /opt/career-search/app
chmod -R a+rX /opt/career-search/app
python3 -m venv /opt/career-search/venv
/opt/career-search/venv/bin/pip install --require-hashes \
    -r /opt/career-search/app/deploy/aws/requirements.txt
/opt/career-search/venv/bin/pip install --no-deps --no-build-isolation /opt/career-search/app
/opt/career-search/venv/bin/pip check
chmod -R a+rX /opt/career-search/venv

# Digest obtained from the official OpenAI v0.0.14 GitHub release asset.
archive=$(mktemp)
trap 'rm -f -- "$archive"' EXIT
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
    https://github.com/openai/tunnel-client/releases/download/v0.0.14/tunnel-client-v0.0.14-linux-amd64.zip \
    --output "$archive"
printf '%s  %s\n' '15bd17e805cad39d412199115bb9e10a978dd35258a114cdf25dd2ae6681c7d3' "$archive" \
    | sha256sum --check --status
unzip -q "$archive" -d /opt/openai-tunnel
chmod -R a+rX /opt/openai-tunnel
chmod 0755 /opt/openai-tunnel/tunnel-client /opt/openai-tunnel/cloudflared
/opt/openai-tunnel/tunnel-client --version

install -m 0600 "$source_dir/deploy/aws/service.env.example" /etc/career-search/service.env
install -m 0600 "$source_dir/deploy/aws/tunnel.env.example" /etc/career-search/tunnel.env
install -m 0644 "$source_dir"/deploy/aws/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/career-{search,watcher,backup,tunnel}.service \
    /etc/systemd/system/career-{watcher,backup}.timer
printf '%s\n' "$1" > /opt/career-search/REVISION
chmod 0644 /opt/career-search/REVISION
printf '%s\n' 'Installed and validated. Services are not enabled or started.' \
    'Next: transfer a consistent database backup, configure the tunnel ID and private key,' \
    'stop the old tunnel runtime, then follow deploy/aws/README.md for activation and checks.'
