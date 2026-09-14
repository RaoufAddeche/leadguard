# Deployment — VPS + DuckDNS

Production URL: **https://leadguard.duckdns.org** (basic auth).

## Topology

The VPS already hosts other stacks. LeadGuard slots in without touching them:

```
Internet ──► portfolio-caddy (:80/:443, TLS + basic auth)
                   │  docker network: portfolio_portfolio_net
                   ▼
          leadguard-frontend (nginx: SPA + /api proxy)
                   │  docker network: leadguard_leadguard_net (private)
                   ├──► leadguard-backend (uvicorn :8000)
                   └──► leadguard-db (postgres)
```

Two invariants keep the cohabitation safe:

1. **No port is published on the host.** Caddy is the only public entrypoint,
   and only `leadguard-frontend` is exposed to it. The API and the database are
   unreachable from outside the private network.
2. **Every service is prefixed `leadguard-`.** On the shared Caddy network the
   names `backend`, `frontend` and `db` already belong to the portfolio stack;
   reusing one would make Docker's DNS round-robin between two applications.
   This is also why `nginx.conf` takes its upstream from `$BACKEND_UPSTREAM`
   instead of hardcoding `backend:8000`.

## Prerequisites

* A DuckDNS subdomain pointing at the VPS IP. Beware: the DuckDNS web form
  prefills *your browser's* IP, not the server's. Fix it from the VPS with
  `curl "https://www.duckdns.org/update?domains=leadguard&token=<token>&ip=46.225.117.160"`
  (expect `OK`), and check with `getent hosts leadguard.duckdns.org` — Caddy
  cannot obtain a certificate until the record points at the VPS.
* `portfolio-caddy` running (it owns :80/:443 and the ACME certificates).
* The `portfolio_portfolio_net` docker network (created by the portfolio stack).

## First deploy

```bash
# 1. From the workstation — ship the working tree (uncommitted changes included)
rsync -az --delete \
  --exclude '.git/' --exclude 'node_modules/' --exclude 'dist/' \
  --exclude '.venv/' --exclude '__pycache__/' --exclude '.pytest_cache/' \
  --exclude '*.db' --exclude '.env' --exclude 'volumes/' \
  ./ trader@46.225.117.160:~/leadguard/

# 2. On the VPS — configure
cd ~/leadguard
cp .env.vps.example .env && chmod 600 .env
#   POSTGRES_PASSWORD: openssl rand -hex 24
#   AI_PROVIDER=mock needs no key; openai/anthropic need theirs.

# 3. Build and start
docker compose -f docker-compose.vps.yml up -d --build

# 4. Wait for the startup seed, then check
docker logs -f leadguard-backend       # until "Application startup complete"
docker exec leadguard-frontend wget -qO- http://127.0.0.1/api/leads/stats
```

## Expose it through Caddy

Append to `~/portfolio/Caddyfile` (back it up first — a syntax error takes down
every site Caddy serves):

```caddyfile
leadguard.duckdns.org {
	encode gzip zstd
	basic_auth {
		"<username>" <bcrypt-hash>
	}
	reverse_proxy leadguard-frontend:80
}
```

Quote the username if it contains a space. Generate the hash, validate, then
reload — **never reload without validating**:

```bash
docker exec portfolio-caddy caddy hash-password --plaintext 'the-password'
#   the credentials in use are kept in ~/leadguard/.caddy-basicauth (chmod 600)
cp ~/portfolio/Caddyfile ~/portfolio/Caddyfile.bak.$(date +%s)
docker exec portfolio-caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec portfolio-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

Caddy requests the Let's Encrypt certificate on the first request, so the
subdomain must already resolve to the VPS: `getent hosts leadguard.duckdns.org`.

## Update

```bash
rsync ...                                              # same command as above
ssh trader@46.225.117.160 'cd ~/leadguard && \
  docker compose -f docker-compose.vps.yml up -d --build'
```

Rolling back is `git checkout` + rsync + the same command: the images are built
from the synced tree, so the tree is the source of truth.

## Operations

| Task | Command (on the VPS, from `~/leadguard`) |
| --- | --- |
| Logs | `docker logs -f leadguard-backend` |
| Status | `docker compose -f docker-compose.vps.yml ps` |
| Restart | `docker compose -f docker-compose.vps.yml restart` |
| Reset the demo data | `docker restart leadguard-backend` (re-seeds) |
| Stop | `docker compose -f docker-compose.vps.yml down` |
| Wipe the database too | `... down -v && rm -rf volumes/postgres_data` |
| Free disk after builds | `docker builder prune -f --filter until=72h` |
| Change the dashboard password | re-hash, edit `~/portfolio/Caddyfile`, validate, reload |

**`SEED_ON_STARTUP=true` resets the database on every start.** The seed truncates
before inserting, so a restart discards leads created from the UI and re-runs one
AI call per seeded lead (~15, a few cents at most on `gpt-4o-mini`). It also
delays readiness by ~30s, because the seed runs inside the FastAPI lifespan,
before the app accepts connections. Set `SEED_ON_STARTUP=false` in `.env` to keep
visitor data and start instantly.

## Resource budget

The VPS runs several stacks on 3.7 GB of RAM, hence the `mem_limit` on each
service (db 256m / backend 384m / frontend 64m — ~130 MB actually used). The
disk sits around 80%: `docker builder prune` before a build if it gets tight,
and `postgres:15` is deliberately reused from another stack rather than pulling
a second Postgres image.
