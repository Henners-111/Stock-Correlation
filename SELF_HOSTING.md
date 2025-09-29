Self-hosting guide (Nginx Proxy Manager + Cloudflare)

Overview
- Two containers via docker-compose:
  - backend: FastAPI on 8000
  - frontend: Nginx serving static files on 8080
- Put both behind Nginx Proxy Manager (NPM) with Cloudflare DNS.

Quick start
1) Clone repo to your Docker host
2) Create .env (optional) to set CORS origins for backend:
   ALLOW_ORIGINS=https://stock.nethercot.uk,https://api.stock.nethercot.uk
3) Launch containers
   docker compose up -d
4) Verify locally:
   - Frontend: http://<host>:8080
   - Backend:  http://<host>:8000/

Nginx Proxy Manager (NPM)
- Create Proxy Host for frontend:
  - Domain Names: stock.nethercot.uk
  - Scheme: http, Forward Hostname/IP: <docker-host-ip>, Forward Port: 8080
  - Enable Websockets
  - SSL tab: Request a new SSL certificate (Let's Encrypt), Force SSL, HTTP/2, HSTS
- Create Proxy Host for backend API:
  - Domain Names: api.stock.nethercot.uk
  - Scheme: http, Forward Hostname/IP: <docker-host-ip>, Forward Port: 8000
  - Enable Websockets
  - SSL tab: Request certificate, Force SSL, HTTP/2, HSTS

Cloudflare DNS
- Add two A records (or proxied orange-cloud):
  - stock  -> your public IP
  - api    -> your public IP
- If using the Cloudflare proxy (orange cloud ON), ensure NPM obtains certs successfully. If issues, temporarily gray-cloud OFF to issue cert, then re-enable.

Frontend config
- The frontend uses window.location.hostname to decide API base and points to https://api.stock.nethercot.uk in production. No changes needed.

Backend CORS
- Set allowed origins via env variable when needed:
  - In docker-compose.yml, set environment:
    ALLOW_ORIGINS=https://stock.nethercot.uk,https://api.stock.nethercot.uk

Updating
- Pull latest repo and restart:
  docker compose pull
  docker compose up -d --build

Troubleshooting
- 502 in NPM: Check containers are running: docker ps
- CORS errors: Confirm ALLOW_ORIGINS includes your frontend origin exactly (scheme + domain)
- Mixed content: Ensure you access frontend via HTTPS and API via HTTPS through NPM.
