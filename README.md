# Virtual Card Creator

Automates creating virtual cards on Mastercard Smart Data (bulk purchase
requests) and saves each card's details to MongoDB. Includes a React +
Flask web UI so you don't have to run scripts by hand.

**This drives your real Mastercard Smart Data account** via a headless
Chrome browser. You enter your ICICI User ID/Password/OTP in the web app
itself, and it types them into the real bank page for you — nothing is
sent anywhere except from your browser to your own backend to your own
Chrome instance. The browser runs headless (no visible window) since
every interaction is driven through the web UI — this also means it runs
fine on a real server with no display attached.

## Project structure

```
backend/    Python backend -- Flask API + Playwright automation
frontend/   React web UI (Vite)
```

## Prerequisites

- Python 3.11+ (`python --version`)
- Node.js + npm (`node --version`)
- Google Chrome (or Chromium) installed
- A MongoDB database (e.g. a free MongoDB Atlas cluster) — **required**;
  card creation is blocked if the database isn't reachable
- A Mastercard Smart Data account with permission to create purchase
  requests (Company Program Administrator or similar)

## Setup (one-time)

```
cd backend
pip install -r requirements.txt
copy config.example.json config.json
copy auth.example.json auth.json
copy .env.example .env
cd ../frontend
npm install
```

- `backend/config.json` holds your default card field values (name,
  email, amounts, etc.) so you don't retype them every time. Edit it, or
  just fill the form in the web UI once — it saves back automatically.
- `backend/auth.json` holds the username/password for the app's own
  login screen (this is separate from your bank login). Edit it to set
  your own credentials.
- `backend/.env` — set `MONGODB_URI` (and optionally `MONGODB_DB_NAME`)
  to your own MongoDB connection string. Every created card is saved
  here; nothing is saved locally anymore.

If Playwright complains it can't find Chrome, run:
```
python -m playwright install chrome
```
(This uses your regular installed Chrome, not a separate download, as
long as Chrome is already on your machine. On a Linux server, install
`google-chrome-stable` or `chromium` via your package manager instead —
`launch_browser.py` checks common install paths for all three platforms.)

## Running it

Open **two** terminal windows:

**Terminal 1 — backend API** (from `backend/`)
```
python app.py
```
Runs on http://localhost:5000

**Terminal 2 — frontend** (from `frontend/`)
```
npm run dev
```
Runs on http://localhost:5173

Then open **http://localhost:5173** in your browser.

You don't need to start the automation browser yourself — the app
launches it automatically (via `launch_browser.py`, headless) whenever
it's needed.

## Using it

1. **App login** — log in with the credentials from `backend/auth.json`.
   This takes you straight to the **Dashboard**.
2. **Dashboard** — total cards created and a trend chart, pulled from
   MongoDB. **Download** — filter card history by date/card number and
   export it as Excel (generated fresh from the database each time).
   Neither of these needs a bank login.
3. **Cards** tab — this is the only part that needs the bank connected.
   Pick a bank from the **header dropdown** (only ICICI is wired up),
   enter your Smart Data User ID/Password (the app fills these into the
   real, headless browser for you), enter the OTP if prompted, then fill
   in the card fields and click **Create Cards**. The first time, you'll
   get a confirmation popup to double-check everything.
4. It fills and submits the form that many times, showing live progress
   and logs, with a **Cancel** button to stop early if needed. Each
   card's details (card number, expiry, CVC, etc.) are saved to MongoDB
   as soon as it's created and shown as card tiles on the page.

## Deploying to a VPS

This runs as **one process** in production: `gunicorn` serves both the
API and the built React app, and auto-launches the headless browser on
startup. Assumes a Debian/Ubuntu VPS with a regular (non-root) user with
sudo access.

**1. Install system packages** (one-time, as root/sudo)
```
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm git nginx
# Chrome (or use `sudo apt install -y chromium` instead):
curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb
sudo apt install -y /tmp/chrome.deb
```

**2. Clone the repo and set up secrets** (these are gitignored — they
don't come from GitHub, you recreate them on the server)
```
git clone https://github.com/<you>/<repo>.git virtual-card-creator
cd virtual-card-creator/backend
cp config.example.json config.json
cp auth.example.json auth.json
cp .env.example .env
nano auth.json   # set your real app-login username/password
nano .env        # set your real MONGODB_URI
```
Also add the VPS's outbound IP to **MongoDB Atlas → Network Access**, or
the app won't be able to reach the database at all.

**3. Install dependencies and build the frontend**
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install-deps   # system libs Chrome needs to run headless
cd ../frontend
npm install
npm run build
```

**4. Test it manually once** before wiring up systemd
```
cd ../backend
chmod +x run_prod.sh
./run_prod.sh
```
In another terminal: `curl http://127.0.0.1:5000/` should return HTML
(the built frontend). Ctrl+C to stop once confirmed.

**5. Make it persistent with systemd**
```
sudo cp ../deploy/virtual-card-creator.service /etc/systemd/system/
sudo nano /etc/systemd/system/virtual-card-creator.service
# edit User, WorkingDirectory, and the venv path to match your server
sudo systemctl daemon-reload
sudo systemctl enable --now virtual-card-creator
sudo systemctl status virtual-card-creator
```

**6. Put nginx in front (public port + HTTPS)**
```
sudo cp ../deploy/nginx.conf.example /etc/nginx/sites-available/virtual-card-creator
sudo nano /etc/nginx/sites-available/virtual-card-creator   # set server_name
sudo ln -s /etc/nginx/sites-available/virtual-card-creator /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.example.com
```

**7. Lock down the firewall** — only expose what needs to be public
```
sudo ufw allow 22    # SSH
sudo ufw allow 80    # HTTP (certbot redirects to 443 after step 6)
sudo ufw allow 443   # HTTPS
sudo ufw enable
```
Ports **5000** (Flask/gunicorn) and **9222** (Chrome's remote debugging
port) must stay closed to the public internet — `ufw` blocks everything
not explicitly allowed by default, so as long as you don't add rules for
them, they're already safe. Anyone who could reach 9222 would fully
control the browser session logged into your real bank account.

**Redeploying after code changes:**
```
cd virtual-card-creator && git pull
cd backend && source venv/bin/activate && pip install -r requirements.txt
cd ../frontend && npm install && npm run build
sudo systemctl restart virtual-card-creator
```

## Files (backend/)

- `app.py` — Flask API (auth, browser lifecycle, card creation, ICICI login/OTP, card history); also serves the built frontend in production
- `automate.py` — Playwright logic for filling/submitting the card form
- `icici_login.py` — Playwright logic for the ICICI User ID/Password/OTP flow
- `launch_browser.py` — launches the headless Chrome instance used for automation
- `db.py` — MongoDB layer (`save_card`, `get_all_cards`, `is_connected`)
- `run_prod.sh` — production start script (gunicorn), used by the systemd service
- `config.json` / `auth.json` / `.env` — local settings (not committed to git — contain personal info)
- `diagnose*.py`, `explore.py` — one-off scripts used to inspect the bank site's DOM during development
- `gui.py` — an earlier desktop (Tkinter) version of the UI; the web UI is the current one

`deploy/` (project root) — `nginx.conf.example` and
`virtual-card-creator.service` templates for the VPS setup above.

## Architecture

```
React (frontend, :5173)  --fetch/JSON-->  Flask API (backend, :5000)
                                                |
                                                |-- Playwright (CDP, :9222) --> headless Chrome --> Mastercard Smart Data
                                                |
                                                +-- pymongo --> MongoDB (the only place card data is stored)
```

- The **frontend never talks to the bank site or MongoDB directly** — it
  only ever calls the Flask API. Flask is the only thing that drives
  Playwright and MongoDB.
- **Chrome runs as its own long-lived, headless process**
  (`launch_browser.py`), controlled remotely over Chrome DevTools
  Protocol on port 9222. Flask attaches to it fresh on each relevant
  request rather than owning the browser itself — this is what lets you
  stay logged in across many separate API calls.
- **Auth** is a simple bearer token: `POST /login` returns a token,
  every other endpoint requires `Authorization: Bearer <token>` (checked
  by the `@require_auth` decorator against an in-memory token set).
- **Long-running actions are polled, not blocking requests.** E.g.
  `POST /create` starts a background thread and returns immediately;
  the frontend then polls `GET /status` every second for live log lines
  and progress until `running` flips back to `false`. Same pattern for
  `GET /browser-status` while waiting for the browser/bank login.
- **Card creation is gated on the database.** `POST /create` first
  checks MongoDB is actually reachable (not just configured) and refuses
  to start if it isn't — cards are never created without a durable place
  to record them.

### Card creation, step by step

1. Frontend `POST /create` with all field values + count.
2. `app.py` checks MongoDB is reachable, saves the fields to
   `config.json` (so they're pre-filled next time), tags the request
   with `created_by` (the Description field's value), and starts a
   background thread.
3. That thread (`automate.run_batch`) attaches to the running headless
   Chrome via CDP and, for each card: navigates the menu, fills every
   field by its DOM id, submits, and scrapes the card number/expiry/CVC
   back out of the confirmation page. You can cancel between cards via
   `POST /cancel`.
4. Each card is saved to MongoDB immediately after creation — so even if
   a later card in the batch fails, the earlier ones are already safely
   recorded.
5. Progress lines accumulate in a shared, lock-protected log list that
   `GET /status` exposes — that's what powers the live Activity Log and
   progress bar in the UI.

### MongoDB document shape

```json
{
  "card_alias": "Nabin_8002",
  "card_number": "5405441230015394",
  "card_amount": "600000.00",
  "expiry": "07/28",
  "cvc": "180",
  "billing_name": "Dashmobiles Private Ltd",
  "description": "PRAVESH",
  "created_by": "PRAVESH",
  "created_at": "2026-07-23T10:15:32.123Z"
}
```

- `GET /api/cards` — returns stored cards as JSON, newest first. Accepts
  `date_from`, `date_to` (`YYYY-MM-DD`), and `search` (matches card
  number or alias) query params.
- `GET /api/cards/download` — same filters, but rebuilds an `.xlsx` file
  **from the database** on the fly and streams it back as a download.

## A note on the data

Every card record includes the full virtual card number and CVC. This
data lives only in your own MongoDB database now — keep your connection
string private (`backend/.env` is gitignored) and don't expose the
database or this app's API publicly without adding real authentication
hardening first.
