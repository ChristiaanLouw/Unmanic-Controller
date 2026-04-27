# Unmanic Controller

Small Flask controller that listens for Plex webhook events and pauses or resumes all Unmanic workers through the Unmanic API.

When playback starts in Plex, the controller pauses Unmanic workers. When playback pauses/stops/scrobbles, it starts a configurable resume timer and resumes the workers when the timer expires.

## What You Connect

- Plex: add the controller webhook URL in Plex settings.
- Unmanic: configure the Unmanic URL and optional credentials in the controller web UI.
- Server: run the container with Docker Compose on Unraid, Linux, Windows, or any Docker host.

## Files

- `docker-compose.yml` - portable default Docker Compose service.
- `docker-compose.unraid-static-ip.example.yml` - optional Unraid custom network/static IP override.
- `.env.example` - configurable ports, timezone, and Flask secret.
- `Dockerfile` and `requirements.txt` - reusable Python runtime image.
- `Container/controller.py` - web UI, Plex webhook listener, and Unmanic API control.
- `Container/settings.example.json` - safe template for runtime settings.
- `Container/settings.json` - safe default runtime settings.
- `Container/static/ui.html` - web UI.
- `Container/logs/` - local API and webhook logs, ignored by Git.

## Quick Start

```sh
cp .env.example .env
cp Container/settings.example.json Container/settings.json
docker compose up -d --build
```

Web UI:

```text
http://YOUR_DOCKER_HOST:8080
```

Plex webhook URL:

```text
http://YOUR_DOCKER_HOST:9777
```

## Configuration

Edit `.env` to change container ports and timezone:

```env
TZ=Africa/Johannesburg
WEB_PORT=8080
WEBHOOK_PORT=9777
SECRET_KEY=replace-with-a-long-random-string
```

Edit `Container/settings.json` directly, or log into the web UI and use the Settings page.

Default web UI login from `settings.example.json`:

```text
admin / admin
```

Change it after first login.

## Unraid

See `UNRAID.md` for both the normal bridge install and the optional custom network/static IP setup.
