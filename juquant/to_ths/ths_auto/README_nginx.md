# nginx reverse proxy + token auth - deployment guide

## Files

| File | Purpose |
|------|---------|
| `setup_nginx.bat` | One-click download, install, configure, start nginx (with token generation) |
| `manage_nginx.bat` | nginx start / stop / reload / status |

## Install steps

1. Upload `setup_nginx.bat` to the ECS (any folder, e.g. `C:\`).
2. Right-click -> Run as administrator (the script checks admin rights).
3. The script will:
   - Generate a 32-char random token (or use your custom one)
   - Download nginx 1.30.5 stable and extract to `C:\nginx`
   - Write `nginx.conf` with token auth
   - Validate config, start nginx, run 401/200 checks
   - Save the token to `C:\nginx\token.txt`

## Architecture

```
JoinQuant cloud --HTTP(80, X-Auth-Token)--> ECS nginx --> THSAutoTrader(127.0.0.1:5000)
```

- nginx listens on `80` and checks the `X-Auth-Token` header.
- `/health` is public (for health checks); all other paths require a valid token.
- THSAutoTrader backend listens on `127.0.0.1:5000` only.

## Key: restrict THSAutoTrader to localhost

THSAutoTrader's Flask default host is `0.0.0.0`. Change it to `127.0.0.1`,
otherwise port 5000 is exposed directly and bypasses nginx auth.

Two options (pick one):

### Option 1: edit code
Change `host='0.0.0.0'` to `host='127.0.0.1'` where Flask starts.

### Option 2: security group only (recommended, no code change)
Open ONLY port 80 in the security group, do NOT open 5000.
Then external traffic can only reach nginx.

## Security group

| Direction | Port | Source | Note |
|-----------|------|--------|------|
| Inbound | TCP:80 | your egress IP /32 | allow only JoinQuant egress IP |
| Inbound | TCP:5000 | not open | backend not exposed |

> Get egress IP using a China-reachable endpoint (in JoinQuant):
> ```python
> import requests
> print(requests.get("https://api.ip.sb/ip", timeout=10).text)
> ```

## Daily management

```bat
C:\nginx\manage_nginx.bat status
C:\nginx\manage_nginx.bat reload
C:\nginx\manage_nginx.bat stop
C:\nginx\manage_nginx.bat start
```

## Verify

```python
# In JoinQuant
from ths_client import THSClient
c = THSClient("http://YOUR_ECS_PUBLIC_IP:80", token="<value in C:\nginx\token.txt>")
print(c.health())
```

- Without token -> HTTP 401 unauthorized
- With correct token -> normal business data

## Advanced (optional)

1. **HTTPS**: obtain an SSL cert, add `listen 443 ssl;` in nginx, use https from JoinQuant.
2. **Auto-start on boot**: register nginx as a Windows service via NSSM, or add a
   scheduled task to run `C:\nginx\nginx.exe` at startup.
3. **Rate limit**: add `limit_req_zone` in nginx to prevent abusive high-frequency orders.
