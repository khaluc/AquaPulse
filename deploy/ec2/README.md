# EC2 deployment

The current deployment is available at
https://aquapulse.3.148.215.37.sslip.io/ (reports: `/report`). Caddy provides
automatic HTTPS and certificate renewal. This sslip.io hostname resolves to
3.148.215.37; if the EC2 public IP changes, the hostname and SITE_ADDRESS must
be updated to use the new IP. Browser geolocation requires opening the HTTPS
address and granting location permission.

Use a Linux x86_64 EC2 instance with Docker Engine and Docker Compose installed.
The repository includes the ONNX models needed by the image. Clone it on EC2:

```sh
git clone https://github.com/khaluc/AquaPulse.git
cd AquaPulse
```

Training checkpoints, datasets and local storage remain excluded from Git.
Do not upload local `.env`, virtual environments, or citizen photos.

Allow inbound HTTP (80) and HTTPS (443); allow SSH (22) only from your own IP.
PostgreSQL and the application port are internal to Docker.

From the repository root on EC2:

```sh
cp deploy/ec2/.env.example deploy/ec2/.env
openssl rand -hex 32
# Edit deploy/ec2/.env: set POSTGRES_PASSWORD to the generated value.
# Configure reviewer tokens using the format documented in the root .env.example.
docker compose --env-file deploy/ec2/.env -f deploy/ec2/compose.yaml up -d --build
docker compose --env-file deploy/ec2/.env -f deploy/ec2/compose.yaml ps
curl --fail http://localhost/health
```

For HTTPS, point a domain's DNS at the EC2 public IP, set SITE_ADDRESS to that
domain (without a scheme), then run the compose command again. Caddy obtains
and renews certificates; both 80 and 443 must be accessible.

Named volumes preserve the database, uploaded photos, and certificates across
container replacements. Back up the database and photos separately. Do not use
`docker compose down -v` unless you intend to delete those volumes.

This deployment creates a fresh database. Existing local reports and photos
require a separate migration. Vision descriptions are disabled by default;
detector and water segmentation remain enabled. Configure a vision provider
in deploy/ec2/.env if needed.
