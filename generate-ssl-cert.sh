#!/bin/bash
# Generate self-signed SSL certificate for OctoHub

set -e

CERT_DIR="nginx/ssl"
DAYS_VALID=365

echo "🔐 Generating self-signed SSL certificate for OctoHub..."
echo ""

# Create directory if it doesn't exist
mkdir -p "$CERT_DIR"

# Ask for domain name (optional)
read -p "Enter domain name (or press Enter for 'octohub.local'): " DOMAIN
DOMAIN=${DOMAIN:-octohub.local}

echo ""
echo "Generating certificate for: $DOMAIN"
echo "Valid for: $DAYS_VALID days"
echo ""

# Generate certificate
openssl req -x509 -nodes -days "$DAYS_VALID" -newkey rsa:2048 \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -subj "/CN=$DOMAIN/O=OctoHub/C=IT"

# Set permissions
chmod 644 "$CERT_DIR/fullchain.pem"
chmod 600 "$CERT_DIR/privkey.pem"

echo ""
echo "✅ SSL certificate generated successfully!"
echo ""
echo "Files created:"
echo "  - $CERT_DIR/fullchain.pem (certificate)"
echo "  - $CERT_DIR/privkey.pem (private key)"
echo ""
echo "⚠️  NOTE: This is a self-signed certificate."
echo "   Browsers will show a security warning."
echo "   For production, use Let's Encrypt (see DEPLOYMENT.md)"
echo ""
echo "Next steps:"
echo "  1. docker-compose up -d"
echo "  2. Open https://$DOMAIN"
echo "  3. Accept the security warning in your browser"
echo ""
