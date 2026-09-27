#!/usr/bin/env bash
# Run ON THE SERVER as root: install the app's nginx site and its Let's Encrypt certificate.
# Usage: deploy/nginx-site.sh <your-domain>        (the domain must already point at the server)
# Safe on a shared nginx: it only writes /etc/nginx/sites-available/interview (+ symlink) and a
# certificate for <your-domain>. It reloads nginx (never restarts) and only after `nginx -t`
# passes; on a failed test it puts the previous site file back and leaves nginx untouched.
# Order: HTTP-only site -> certbot (webroot, does not edit nginx files) -> full HTTPS site.
set -euo pipefail
D="${1:?usage: deploy/nginx-site.sh <your-domain>}"
[[ "$D" =~ ^[a-z0-9.-]+$ ]] || { echo "invalid domain: $D"; exit 1; }
[ "$(id -u)" = 0 ] || { echo "run as root"; exit 1; }
cd "$(dirname "$0")"
SITE=/etc/nginx/sites-available/interview
LINK=/etc/nginx/sites-enabled/interview
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
sed "s/INTERVIEW_DOMAIN/$D/g" nginx-interview.conf > "$WORK/full.conf"
awk '{print} /^}/{exit}' "$WORK/full.conf" > "$WORK/http.conf"   # first server block: port 80

install_site() {
  if [ -e "$SITE" ]; then cp "$SITE" "$WORK/previous.conf"; fi
  cp "$1" "$SITE"
  ln -sfn "$SITE" "$LINK"
  if nginx -t; then
    systemctl reload nginx
  else
    echo "nginx -t failed: restoring the previous state, nginx not reloaded"
    if [ -e "$WORK/previous.conf" ]; then cp "$WORK/previous.conf" "$SITE"; else rm -f "$LINK" "$SITE"; fi
    exit 1
  fi
}

if [ ! -e "/etc/letsencrypt/live/$D/fullchain.pem" ]; then
  echo "== 1/3 HTTP-only site for $D"
  install_site "$WORK/http.conf"
  echo "== 2/3 certificate for $D"
  certbot certonly --webroot -w /var/www/certbot -d "$D" --non-interactive --agree-tos \
    --deploy-hook "systemctl reload nginx"
fi
echo "== 3/3 HTTPS site for $D"
install_site "$WORK/full.conf"
echo "DONE: https://$D/"
