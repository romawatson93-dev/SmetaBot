Dev over Tailscale (Variant A)

Goal: Serve https://dev.orbitsend.ru via Traefik on the VDS, proxying to your local machine over Tailscale. This gives a stable HTTPS URL for the WebApp without touching prod.

Steps

1) DNS
- Create an A record: dev.orbitsend.ru -> VDS public IP.

2) Tailscale
- On VDS (Debian/Ubuntu):
  - curl -fsSL https://tailscale.com/install.sh | sh
  - sudo tailscale up --ssh
- On your Windows PC:
  - Install the Tailscale app and sign in with the same account as on VDS.
  - Get your Tailscale IPv4: tailscale ip -4

3) Traefik dynamic config
- Edit infra/traefik/dynamic/dev.yaml and replace 100.100.100.100 with your Windows Tailscale IPv4.

4) Deploy Traefik
- On the VDS in the repo:
  - docker compose pull traefik
  - docker compose up -d traefik
- Traefik file provider is enabled and watches infra/traefik/dynamic; changes apply automatically.

5) Local services
- Run local dev stack (at least userbot on :8001):
  - docker compose -f docker-compose.yml -f docker-compose.dev.yml up userbot
  - Ensure .env.dev has WEBAPP_URL=https://dev.orbitsend.ru/webapp/login

Notes
- Only userbot is routed for dev by default. If you need backend exposed to the WebApp, add another service in dev.yaml (e.g., map /api) or enable CORS and call it via userbot.
- Keep dev and prod bot tokens separate; WebApp Init Data validation must use the dev bot token in dev.
- Traffic over Tailscale is encrypted; no public ports needed on your PC.

