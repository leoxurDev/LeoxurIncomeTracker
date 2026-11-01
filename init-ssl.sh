#!/bin/bash
set -e

echo "===================================================================="
echo "    LEOXUR FINANCIAL TELEMETRY — AUTOMATED SSL BOOTSTRAPPER         "
echo "===================================================================="

# 1. Verify Docker and Docker Compose presence
if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is not installed or not in PATH."
    exit 1
fi

# Detect docker compose plugin vs standalone docker-compose
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "Error: Neither 'docker compose' nor 'docker-compose' was found."
    exit 1
fi

# 2. Check or create .env configuration file
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo "Creating .env from .env.example..."
        cp .env.example .env
    else
        touch .env
    fi
fi

# 3. Retrieve or prompt for Domain Name and ACME Email
DOMAIN_NAME=$(grep -E "^DOMAIN_NAME=" .env | cut -d '=' -f2- | tr -d ' "' || true)
ACME_EMAIL=$(grep -E "^ACME_EMAIL=" .env | cut -d '=' -f2- | tr -d ' "' || true)

if [ -z "$DOMAIN_NAME" ] || [ "$DOMAIN_NAME" = "tracker.yourdomain.com" ]; then
    read -p "Enter your Domain Name (e.g., tracker.mydomain.com or mydomain.com): " INPUT_DOMAIN
    DOMAIN_NAME="$INPUT_DOMAIN"
    sed -i.bak "/^DOMAIN_NAME=/d" .env && rm -f .env.bak
    echo "DOMAIN_NAME=$DOMAIN_NAME" >> .env
fi

if [ -z "$ACME_EMAIL" ] || [ "$ACME_EMAIL" = "admin@yourdomain.com" ]; then
    read -p "Enter your Email Address for SSL expiry alerts: " INPUT_EMAIL
    ACME_EMAIL="$INPUT_EMAIL"
    sed -i.bak "/^ACME_EMAIL=/d" .env && rm -f .env.bak
    echo "ACME_EMAIL=$ACME_EMAIL" >> .env
fi

echo "Target Domain: $DOMAIN_NAME"
echo "Renewal Email: $ACME_EMAIL"

# 4. Prepare required local directories for Certbot challenge and certs
mkdir -p ./webroot/.well-known/acme-challenge
mkdir -p ./certbot-etc/live/"$DOMAIN_NAME"
mkdir -p ./certbot-var
mkdir -p ./logs

# 5. Check if real Let's Encrypt certificates are already provisioned
if [ -f "./certbot-etc/live/$DOMAIN_NAME/fullchain.pem" ]; then
    echo "Real SSL certificates already detected for $DOMAIN_NAME."
    echo "Starting full Docker service cluster..."
    $COMPOSE up -d
    echo "Application running at https://$DOMAIN_NAME"
    exit 0
fi

# 6. Generate temporary dummy self-signed certificate so Nginx can start
echo "Generating temporary boot certificate for Nginx..."
openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -keyout "./certbot-etc/live/$DOMAIN_NAME/privkey.pem" \
    -out "./certbot-etc/live/$DOMAIN_NAME/fullchain.pem" \
    -subj "/CN=localhost" 2>/dev/null

# 7. Start web backend and Nginx reverse proxy
echo "Starting backend and Nginx proxy with initial certificate..."
$COMPOSE up -d db
$COMPOSE up -d web
$COMPOSE up -d nginx

echo "Waiting for services to initialize..."
sleep 6

# 8. Request live certificate from Let's Encrypt via Certbot
echo "Requesting official Let's Encrypt certificate for $DOMAIN_NAME..."
$COMPOSE run --rm certbot certonly --webroot \
    --webroot-path=/var/www/certbot \
    --email "$ACME_EMAIL" \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d "$DOMAIN_NAME"

# 9. Reload Nginx to activate the real SSL certificate
echo "Reloading Nginx with new live certificate..."
$COMPOSE exec nginx nginx -s reload

# 10. Start Certbot auto-renewal background service
$COMPOSE up -d certbot

echo "===================================================================="
echo "  SUCCESS! Leoxur Financial Telemetry is LIVE and SECURED!          "
echo "  URL: https://$DOMAIN_NAME                                         "
echo "===================================================================="
