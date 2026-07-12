#!/bin/bash

# Configuration
read -p "Enter your Domain Name (e.g. tracker.yourdomain.com): " domain
read -p "Enter your Email Address for SSL renewal notifications: " email

if [ -z "$domain" ] || [ -z "$email" ]; then
    echo "Error: Domain and Email are required parameters."
    exit 1
fi

# Set environmental values for docker-compose substitution
export DOMAIN_NAME=$domain

# Create local webroot directory for certbot challenge verification
mkdir -p ./webroot/.well-known/acme-challenge

# 2. Check if certificates already exist
if [ -d "./certbot-etc/live/$domain" ]; then
    echo "SSL certificates already exist for $domain. Starting containers..."
    docker-compose up -d nginx
    exit 0
fi

# 3. Create dummy self-signed certificate to allow Nginx to start
echo "Generating fallback dummy certificate for Nginx start..."
path="/etc/letsencrypt/live/$domain"
mkdir -p "./certbot-etc/live/$domain"

openssl req -x509 -nodes -newkey rsa:4096 -days 1 \
    -keyout "./certbot-etc/live/$domain/privkey.pem" \
    -out "./certbot-etc/live/$domain/fullchain.pem" \
    -subj "/CN=localhost"

# 4. Start Nginx
echo "Starting Nginx with placeholder certificates..."
docker-compose up -d nginx

# 5. Delete dummy certificates
echo "Removing dummy certificates..."
rm -rf "./certbot-etc/live/$domain"

# 6. Request real Let's Encrypt certificates
echo "Requesting live Let's Encrypt certificate for $domain..."
docker-compose run --rm certbot certonly --webroot \
    --webroot-path=/var/www/certbot \
    --email "$email" \
    --agree-tos \
    --no-eff-email \
    -d "$domain"

# 7. Reload Nginx to load live certificates
echo "Reloading Nginx with new live SSL certificates..."
docker-compose exec nginx nginx -s reload

echo "Success! Leoxur Income Tracker is now running securely on https://$domain"
