# Hargeisa Local Government – Tax Collection System

An open-source web platform that replaces manual (paper) tax collection for the
Hargeisa local government in Somaliland. Tax collectors record payments on
their phones in the field, with GPS. Supervisors, managers and auditors see
live totals, maps and exports.

Built only with free, open-source software: **Python / Django**, **PostgreSQL**,
**Gunicorn**, **Caddy**, **Chart.js** and **Leaflet/OpenStreetMap**.

---

## Why your `http://localhost:8080/collector/` only opens on your PC

`localhost` always means **"this same device"**. When a phone opens
`localhost:8080`, it looks for a server *on the phone*, finds nothing, and fails.
There are three levels of fixing this:

| Level | Who can open it | How |
|-------|-----------------|-----|
| 1. Same Wi-Fi (testing) | Phones and laptops on your home/office Wi-Fi | Run the server on `0.0.0.0` and open your PC's IP address, e.g. `http://192.168.1.25:8080/collector/` |
| 2. Temporary public link (demo) | Anyone with the link, while your PC is on | A tunnel such as `cloudflared tunnel --url http://localhost:8080` |
| 3. **Real deployment (production)** | All collectors, anywhere, 24/7 | Put it on a server with a domain and HTTPS (see [Deploying online](#deploying-online)) |

**Level 1, step by step:**

```bash
python manage.py runserver 0.0.0.0:8080
```

1. Find your PC's IP address: Windows `ipconfig` (look for "IPv4 Address"), Mac/Linux `ip addr` or `ifconfig`.
2. On the phone (same Wi-Fi), open `http://<that-ip>:8080/collector/`.
3. If it still doesn't load, allow port 8080 through the Windows/Mac firewall.

> **Phones only share GPS location with HTTPS sites** (or `localhost`). On a
> plain `http://192.168…` address the payment still saves, but without
> latitude/longitude/altitude. Level 2 or 3 gives you HTTPS.

Your PC at home is not a server: it switches off, the home internet has no
fixed address, and if the hard drive fails, all tax records are lost.
For real use, go to level 3.

---

## What the system does

### Roles (role-based access)

| Role | Record payments | Sees | Void receipts | Reports & CSV export | Admin site |
|------|:---:|------|:---:|:---:|:---:|
| **Tax collector** | ✅ (own department's taxes, own district) | Only their own payments | – | – | – |
| **Supervisor** | ✅ (can give larger discounts) | Their department | ✅ | ✅ | – |
| **Revenue manager** | – | Everything | ✅ | ✅ | – |
| **Auditor** | – | Everything (read-only) | – | ✅ | – |
| **System administrator** | – | Everything | ✅ | ✅ | ✅ users, tax types, locations |

These rules are enforced on the server for every page and every API call, not just hidden in the menu.

### Data recorded for every payment

| Field | Notes |
|-------|-------|
| Receipt number | Automatic and unique, e.g. `HGA-2026-00000123` |
| Tax collector ID and name | From the logged-in account (cannot be typed or faked) |
| Department | Taken from the tax type |
| Taxpayer | Optional link to a registered taxpayer (`TP-00000001`), or a walk-in name and phone |
| Tax type and period | e.g. Residential property tax, 2026 |
| Tax amount and currency | Somaliland Shilling (SLSH) or US Dollar |
| Discount | None / percentage / fixed amount, with a required reason. Collectors are capped per tax type; above the cap a supervisor must record it |
| Amount paid | Calculated by the server: amount − discount |
| Payment system | Cash, **ZAAD**, **eDahab**, bank transfer, cheque. Mobile money and bank payments require the transaction reference so they can be reconciled |
| Date and time of collection | |
| Village → district → city → State/Region → country | Stored once in a location hierarchy (Somaliland › Maroodi Jeex › Hargeisa › district › village) |
| Latitude, longitude, altitude, GPS accuracy | Captured automatically from the phone |
| Status | Completed or **voided** (with who, when and why) |

### Extra structures added

* **Taxpayer register**: people and businesses with national ID, phone, property number and location, so payment history builds up per taxpayer.
* **Tax types**: each with department, default amount, currency, frequency (daily, monthly, annual…) and maximum collector discount.
* **Audit log**: every login, failed login, payment, void and export, with user and IP address. It cannot be edited.
* **No editing or deleting of payments.** Mistakes are *voided* and the original stays visible. This is the main protection against fraud.
* **Duplicate protection**: each form or app submission carries a unique ID, so a retry on a weak mobile connection never records the payment twice.

### Pages

| URL | Purpose |
|-----|---------|
| `/collector/` | Collector's day: today's totals and recent receipts |
| `/collector/new/` | Mobile payment form with automatic GPS and live "to pay" total |
| `/receipt/<number>/` | Printable receipt (works with small Bluetooth receipt printers) |
| `/taxpayers/new/` | Register a taxpayer |
| `/collections/` | Search and filter payments, CSV export |
| `/dashboard/` | Revenue by day, department, tax type, payment method, district and collector |
| `/map/` | Map of where payments were collected |
| `/admin/` | Manage users, roles, departments, tax types and locations |
| `/api/` | REST API for a future Android app or other systems |

### REST API (for a future mobile app)

```
POST /api/auth/token/        {"username": "...", "password": "..."}  -> {"token": "..."}
GET  /api/me/
GET  /api/tax-types/   GET /api/villages/
GET  /api/collections/?since=2026-10-01&status=COMPLETED&search=HGA-2026
POST /api/collections/       (send your own client_uuid: retries are safe)
POST /api/collections/<id>/void/   {"reason": "..."}   (supervisor+)
GET/POST /api/taxpayers/
```
Send `Authorization: Token <token>` on every request.

---

## Running it on your computer

Requirements: Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo                      # sample Hargeisa data + demo users
python manage.py seed_demo --collections 20000  # optional: fake payments to test speed
python manage.py runserver 0.0.0.0:8080
```

Open http://localhost:8080 and log in with one of the demo users
(`admin`, `manager`, `auditor`, `supervisor`, `collector1`, `collector2`),
all with password `ChangeMe-2026`.

Run the tests: `python manage.py test`

> The districts, villages and tax amounts in `seed_demo` are **samples**.
> Replace them with the municipality's official lists in `/admin/` before real use.

---

## Deploying online

This is what makes it work on every collector's phone. You need:

1. **A server (VPS)**: Ubuntu 24.04, 2 CPU, 4 GB RAM, 80 GB disk is plenty to start. Any provider works (local Somaliland data centres, or Hetzner, DigitalOcean, AWS…). Government data-hosting rules may say where it must be.
2. **A domain name**, e.g. `tax.hargeisa.gov.so` (or any domain you own), with a DNS **A record** pointing to the server's IP address.

Then, on the server:

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh

# 2. Get the code
git clone <this-repository-url> /opt/tax && cd /opt/tax

# 3. Configure
cp .env.example .env
nano .env
#   DJANGO_SECRET_KEY = a long random string
#                       (python3 -c "import secrets; print(secrets.token_urlsafe(50))")
#   DJANGO_ALLOWED_HOSTS = tax.hargeisa.gov.so
#   DJANGO_CSRF_TRUSTED_ORIGINS = https://tax.hargeisa.gov.so
#   SITE_ADDRESS = tax.hargeisa.gov.so      <- Caddy gets a free HTTPS certificate
#   DJANGO_SECURE = True
#   POSTGRES_PASSWORD and the password inside DATABASE_URL = the same strong password

# 4. Start (PostgreSQL + app + HTTPS web server)
docker compose up -d --build

# 5. Create the first real administrator, load locations and tax types
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo --no-users

# 6. Nightly backups
crontab -e   # add:  0 2 * * * /opt/tax/deploy/backup.sh
```

Every collector can now open `https://tax.hargeisa.gov.so/collector/` on their
phone, and GPS works because the site uses HTTPS. On Android, choose "Add to Home
screen" in Chrome so it opens like an app.

### Handling hundreds of thousands of people

* PostgreSQL holds millions of payment rows. Every common filter (date, collector, department, district, status, payment method) has an index.
* Lists are paginated and CSV exports are streamed, so large reports do not exhaust server memory.
* The app servers keep no state. When usage grows, raise `GUNICORN_WORKERS`, give the database its own server, or run several `web` containers behind Caddy.
* The seed command can create 20,000+ fake payments in seconds, so you can measure speed before launch.

### Before going live: checklist

- [ ] Delete or change every demo account and password
- [ ] Load the official districts, villages, departments and tax rates
- [ ] HTTPS working, and `DJANGO_DEBUG=False`, `DJANGO_SECURE=True`
- [ ] Backups run every night **and are copied off the server**. Test a restore once
- [ ] Each collector has their own account (never shared), with employee ID, department and district
- [ ] Train collectors; run paper and digital side by side for a few weeks in one district first

---

## Roadmap ideas

* **Offline mode**: an installable app (PWA) that stores payments on the phone when there's no signal and syncs later through the API (the API already deduplicates).
* **ZAAD / eDahab merchant API integration**: confirm mobile-money payments automatically instead of typing the reference.
* **SMS receipts** to the payer's phone.
* **Somali-language interface**: Django's translation system is already enabled.
* **Property register with map polygons** (PostGIS) and yearly assessment and arrears tracking.
* **Daily cash reconciliation**: collectors hand over cash and supervisors confirm totals.

## Project layout

```
config/       settings, URLs
accounts/     users, roles, departments
locations/    country > region > city > district > village
taxes/        tax types, taxpayers, collections, audit log, views, API, tests
templates/    HTML pages
static/       CSS, Chart.js and Leaflet (served locally, no CDN needed)
deploy/       Caddy (HTTPS) config, backup script
```

## License

MIT. Free to use, change and share.
