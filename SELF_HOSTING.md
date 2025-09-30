Self-hosting guide (GitHub Pages + NPM + Cloudflare)

Architecture
- Frontend: served by GitHub Pages from this repo (static assets only).
- Backend: FastAPI app running on your home server (Proxmox VM, bare metal, etc.).
- Routing: Cloudflare DNS → Nginx Proxy Manager (NPM) on your home network → backend service.

1. Frontend on GitHub Pages
- Push this repository to GitHub.
- Settings → Pages → “Deploy from a branch”, select `main` and `/ (root)`.
- Custom domain (optional): add `CNAME` file with `stock.nethercot.uk` (already provided) and create a Cloudflare CNAME record `stock` → `<your-username>.github.io` (orange cloud ON). After Pages issues HTTPS, enable “Force HTTPS”.

2. Backend on your home server
- Install Python 3.10+.
- Clone repo and set up a virtual environment:
```bash
git clone https://github.com/<your-username>/stock-corr-demo.git
cd stock-corr-demo
python3 -m venv .venv
source .venv/bin/activate   # PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
```
- Run the API (foreground test):
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000
```
- For continuous operation create a systemd service, e.g. `/etc/systemd/system/stockcorr.service`:
```
[Unit]
Description=Stock Correlation API
After=network.target

[Service]
User=svc-stockcorr
WorkingDirectory=/opt/stock-corr-demo/backend
Environment="ALLOW_ORIGINS=https://stock.nethercot.uk,https://api.stock.nethercot.uk"
ExecStart=/opt/stock-corr-demo/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```
- Reload and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now stockcorr
```

3. Publish through Nginx Proxy Manager
- In NPM create a Proxy Host `api.stock.nethercot.uk`.
  - Scheme: http
  - Forward Hostname/IP: <backend-local-ip>
  - Forward Port: 8000
  - Enable Websockets
  - SSL tab: Request Let’s Encrypt cert, enable Force SSL, HTTP/2, HSTS

4. Cloudflare DNS
- Record `api` (A or AAAA) → your home public IP (orange cloud ON).
- Record `stock` (CNAME) → `<your-username>.github.io` (or use Pages’ recommended target). Ensure `stock` also has orange cloud ON for proxying.
- If Let’s Encrypt issuance fails, temporarily set the record to gray cloud OFF, issue cert in NPM, then toggle back to orange.

5. Verify
- https://stock.nethercot.uk loads the GitHub Pages frontend.
- The browser fetches data from https://api.stock.nethercot.uk/history… with 200 responses.
- https://api.stock.nethercot.uk/ returns the backend health JSON.

6. Updates
- Frontend: push to GitHub main, Pages redeploys automatically.
- Backend: pull latest code on the server, reinstall requirements if needed, restart systemd service (`sudo systemctl restart stockcorr`).

Troubleshooting
- CORS error: ensure `ALLOW_ORIGINS` includes `https://stock.nethercot.uk` exactly.
- 522/524/502: verify NPM can reach the backend IP/port and the systemd service is running.
- Mixed content: confirm both frontend and API are accessed via HTTPS.
