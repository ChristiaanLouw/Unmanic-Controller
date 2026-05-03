# Unmanic Controller

Small Flask controller that listens for Plex webhook events and pauses or resumes all Unmanic workers through the Unmanic API.

When playback starts in Plex, the controller pauses Unmanic workers. When playback pauses/stops/scrobbles, it starts a configurable resume timer and resumes the workers when the timer expires.

## What You Connect

- Plex: add the controller webhook URL in Plex settings.
- Unmanic: configure the Unmanic URL and optional credentials in the controller web UI.
- Server: run the container with Docker Compose on Unraid, Linux, Windows, or any Docker host.

## Files

- `docker-compose.yml` - portable default Docker Compose service.
- `docker-compose.build.yml` - optional local build override.
- `docker-compose.unraid-static-ip.example.yml` - optional Unraid custom network/static IP override.
- `.env.example` - configurable ports, timezone, and Flask secret.
- `Dockerfile` and `requirements.txt` - reusable Python runtime image.
- `Container/controller.py` - web UI, Plex webhook listener, and Unmanic API control.
- `Container/settings.example.json` - safe template for runtime settings.
- `Container/static/ui.html` - web UI.
- `data/settings.json` - persistent runtime settings, ignored by Git.
- `data/logs/` - persistent API and webhook logs, ignored by Git.

## Quick Start

```sh
cp .env.example .env
mkdir -p data
cp Container/settings.example.json data/settings.json
docker compose up -d --build
```

After the image is published to Docker Hub, you can pull it instead:

```sh
docker compose pull
docker compose up -d
```

For local development builds:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
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

Edit `data/settings.json` directly, or log into the web UI and use the Settings page.

Default web UI login from `settings.example.json`:

```text
admin / admin
```

Change it after first login.

## Plex Webhook Keys

In the web UI, open Settings and generate a named Plex webhook API key for each Plex instance, such as `LouwPlex` or `Shared`.

Use the generated URL as that Plex server's webhook URL:

```text
http://YOUR_DOCKER_HOST:9777/?key=GENERATED_KEY
```

If no webhook keys exist, webhooks are accepted without a key. Once at least one key exists, incoming Plex webhooks must include a valid key.

## Plex Session Monitor

For a central setup that does not require every Plex user to configure webhooks or have Plex Pass, enable Plex Session Monitor in Settings.

Add each Plex server with:

- A friendly name, such as `LouwPlex` or `Shared`.
- The Plex server URL, such as `http://192.168.1.10:32400`.
- A Plex token for that server.

The controller polls `/status/sessions` on each enabled Plex server. If any server has active playback, Unmanic workers are paused. When all monitored servers stop active playback, the normal resume timer is scheduled.

## Unraid

See `UNRAID.md` for both the normal bridge install and the optional custom network/static IP setup.

## Docker Hub Publishing

The GitHub Actions workflow in `.github/workflows/dockerhub.yml` publishes the image to Docker Hub on pushes to `main`, tags like `v1.0.0`, and manual workflow runs.

Add these GitHub repository secrets:

```text
DOCKERHUB_USERNAME
DOCKERHUB_TOKEN
```

Create the token in Docker Hub under Account Settings -> Personal access tokens.
