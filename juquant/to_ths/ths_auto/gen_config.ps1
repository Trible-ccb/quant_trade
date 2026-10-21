# gen_config.ps1
# Generate nginx.conf for THSAutoTrader reverse proxy with token auth.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File gen_config.ps1 -Token "<token>" -ListenPort 80 -BackendPort 5000 -OutFile "C:\nginx\conf\nginx.conf"

param(
    [string]$Token,
    [int]$ListenPort = 80,
    [int]$BackendPort = 5000,
    [string]$OutFile = "C:\nginx\conf\nginx.conf"
)

if (-not $Token) {
    Write-Host "[ERROR] Token is required." -ForegroundColor Red
    exit 1
}

$lines = @(
    "# nginx reverse proxy for THSAutoTrader with token auth",
    "worker_processes  1;",
    "",
    "events {",
    "    worker_connections  1024;",
    "}",
    "",
    "http {",
    "    include       mime.types;",
    "    default_type  application/octet-stream;",
    "    sendfile        on;",
    "    keepalive_timeout  65;",
    "",
    "    access_log  logs/access.log;",
    "    error_log   logs/error.log;",
    "",
    "    server {",
    "        listen       $ListenPort;",
    "        server_name  _;",
    "",
    "        # expected token, must match THSClient token param",
    "        set `$expected_token $Token;",
    "",
    "        # health check is public",
    "        location = /health {",
    "            proxy_pass http://127.0.0.1:$BackendPort;",
    "        }",
    "",
    "        location / {",
    "            # token check via X-Auth-Token header",
    "            if (`$http_x_auth_token != `$expected_token) {",
    "                return 401 unauthorized;",
    "            }",
    "            proxy_pass http://127.0.0.1:$BackendPort;",
    "            proxy_set_header Host `$host;",
    "            proxy_set_header X-Real-IP `$remote_addr;",
    "            proxy_read_timeout  60s;",
    "            proxy_send_timeout  60s;",
    "        }",
    "    }",
    "}"
)

$content = $lines -join [Environment]::NewLine
[System.IO.File]::WriteAllText($OutFile, $content)
Write-Host "[INFO] Config written to: $OutFile"
