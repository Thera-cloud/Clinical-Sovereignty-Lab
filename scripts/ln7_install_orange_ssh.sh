#!/usr/bin/env bash
# Install GREEN's deploy pubkey onto ORANGE so GREEN→10.13.13.5 SSH works.
# Run ONCE from ORANGE console (Hetzner) or any host that already has root on ORANGE:
#   bash scripts/ln7_install_orange_ssh.sh
# Or from GREEN after you temporarily enable password/console:
#   ssh root@10.13.13.5 'bash -s' < scripts/ln7_install_orange_ssh.sh
set -euo pipefail
PUB="${1:-}"
if [[ -z "$PUB" ]]; then
  if [[ -f /tmp/green_ed25519.pub ]]; then
    PUB="$(cat /tmp/green_ed25519.pub)"
  elif [[ -f /root/.ssh/id_ed25519.pub ]]; then
    # When run on GREEN via ssh root@orange 'bash -s' this won't exist on ORANGE —
    # pass the key as $1 instead.
    PUB="$(cat /root/.ssh/id_ed25519.pub)"
  else
    echo "usage: $0 'ssh-ed25519 AAAA... root@green'"
    exit 2
  fi
fi
mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
if grep -qxF "$PUB" /root/.ssh/authorized_keys; then
  echo "already_installed"
else
  echo "$PUB" >> /root/.ssh/authorized_keys
  echo "installed"
fi
