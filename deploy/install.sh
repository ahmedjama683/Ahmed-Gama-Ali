#!/usr/bin/env bash
# One-command installer for a fresh Ubuntu 24.04 server.
#
#   curl -fsSL https://raw.githubusercontent.com/ahmedjama683/Ahmed-Gama-Ali/master/deploy/install.sh -o install.sh
#   sudo bash install.sh
#
# Before running: point your domain's DNS "A record" at this server's IP
# address, otherwise the free HTTPS certificate cannot be issued.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ahmedjama683/Ahmed-Gama-Ali.git}"
APP_DIR="${APP_DIR:-/opt/tax}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Please run as root: sudo bash install.sh" >&2
  exit 1
fi

read -rp "Domain name for the system (e.g. tax.example.com): " DOMAIN
if [ -z "$DOMAIN" ]; then echo "A domain is required." >&2; exit 1; fi
read -rp "Client government name [Hargeisa Local Government]: " CLIENT_NAME
CLIENT_NAME="${CLIENT_NAME:-Hargeisa Local Government}"
read -rp "Operating company name (shown in the footer and on receipts, optional): " OPERATOR_NAME
read -rp "Receipt number prefix [HGA]: " RECEIPT_PREFIX
RECEIPT_PREFIX="${RECEIPT_PREFIX:-HGA}"
read -rsp "GitHub access token (only if the repository is private, else press Enter): " GITHUB_TOKEN
echo

SERVER_IP="$(curl -fsS https://api.ipify.org || true)"
DNS_IP="$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}' || true)"
if [ -n "$SERVER_IP" ] && [ "$SERVER_IP" != "$DNS_IP" ]; then
  echo "WARNING: $DOMAIN points to '${DNS_IP:-nothing}', but this server is $SERVER_IP."
  echo "HTTPS will fail until the DNS A record points here (changes can take up to an hour)."
  read -rp "Continue anyway? [y/N] " ok
  [ "$ok" = "y" ] || exit 1
fi

echo "==> Installing Docker, git and firewall"
apt-get update -q
apt-get install -y -q git curl ufw
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Getting the code into $APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  if [ -n "$GITHUB_TOKEN" ]; then
    # A read-only, fine-grained token limited to this one repository is enough.
    git clone "${REPO_URL/https:\/\//https://x-access-token:$GITHUB_TOKEN@}" "$APP_DIR"
  else
    git clone "$REPO_URL" "$APP_DIR"
  fi
fi
cd "$APP_DIR"

if [ ! -f .env ]; then
  echo "==> Writing configuration (.env) with new random secrets"
  DB_PASSWORD="$(openssl rand -hex 24)"
  SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n=+/')"
  cat > .env <<EOF
DJANGO_SECRET_KEY=$SECRET_KEY
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=$DOMAIN
DJANGO_CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DJANGO_SECURE=True
DATABASE_URL=postgres://tax:$DB_PASSWORD@db:5432/tax
POSTGRES_DB=tax
POSTGRES_USER=tax
POSTGRES_PASSWORD=$DB_PASSWORD
SITE_ADDRESS=$DOMAIN
SYSTEM_NAME=Tax Collection System
CLIENT_NAME=$CLIENT_NAME
OPERATOR_NAME=$OPERATOR_NAME
RECEIPT_PREFIX=$RECEIPT_PREFIX
MAP_CENTER=9.5624,44.0770
EOF
  chmod 600 .env
else
  echo "==> Keeping existing .env"
fi

echo "==> Building and starting (database, app, HTTPS web server)"
docker compose up -d --build

echo "==> Waiting for the app to finish starting"
for _ in $(seq 1 60); do
  if docker compose exec -T web python manage.py check >/dev/null 2>&1; then break; fi
  sleep 2
done
docker compose exec -T web python manage.py migrate --noinput
docker compose exec -T web python manage.py seed_demo --no-users

echo "==> Scheduling nightly backups and location-data cleanup"
chmod +x deploy/backup.sh
( crontab -l 2>/dev/null | grep -v "$APP_DIR" || true
  echo "0 2 * * * $APP_DIR/deploy/backup.sh"
  echo "30 2 * * * cd $APP_DIR && docker compose exec -T web python manage.py purge_location_pings --days 90"
) | crontab -

echo
echo "==> Create the first administrator account"
docker compose exec web python manage.py createsuperuser

cat <<EOF

Done. Open https://$DOMAIN/admin/ and log in with the account you just created.

Next steps:
  1. In Admin, replace the SAMPLE districts, villages and tax amounts with the official ones.
  2. Create one account per staff member, with the right role, department and district.
  3. Copy the files in $APP_DIR/backups to another computer regularly.

Update to a newer version later with:
  cd $APP_DIR && git pull && docker compose up -d --build
EOF
