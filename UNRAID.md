# Unraid Install

## Default bridge install

Use this when port mappings are enough:

```sh
cd /mnt/user/appdata
git clone https://github.com/YOUR-USER/Unmanic-Controller.git
cd Unmanic-Controller
cp .env.example .env
mkdir -p data
cp Container/settings.example.json data/settings.json
docker compose up -d --build
```

## Updating from older versions

Older versions stored runtime settings in `Container/settings.json`, which could be overwritten by source updates. This version stores runtime settings in `data/settings.json`.

Before updating, migrate existing settings once if they still exist:

```sh
cd /mnt/user/appdata/Unmanic-Controller
mkdir -p data
if [ -f Container/settings.json ] && [ ! -f data/settings.json ]; then cp Container/settings.json data/settings.json; fi
docker compose pull
docker compose up -d
```

The container also mounts `Container/` read-only as a legacy settings source. If `data/settings.json` is missing or looks like a fresh default reset, the app will try to recover from `Container/settings.json` or `data/settings.backup.json`.

Once the Docker Hub image is published, use this instead:

```sh
docker compose pull
docker compose up -d
```

If Unraid does not show the WebUI menu or icon after an update, recreate the container from the compose file so Unraid picks up the updated labels:

```sh
docker compose up -d --force-recreate
```

If Unraid still does not refresh the WebUI/icon metadata, remove the container and recreate it from Compose. Your settings and logs live in `data/`, so removing the container does not delete the app configuration.

Open the web UI on:

```text
http://YOUR_UNRAID_SERVER_IP:8080
```

Add this Plex webhook URL:

```text
http://YOUR_UNRAID_SERVER_IP:9777
```

Alternatively, use Plex Session Monitor from the web UI Settings page. Add each Plex instance once with its server URL and token, then the controller will monitor playback centrally without per-user Plex webhooks.

## Optional custom network with static IP

Use this only when you want the controller to have its own LAN IP on an existing Unraid custom Docker network.

Add these lines to `.env`:

```env
UNRAID_DOCKER_NETWORK=br2
UNMANIC_CONTROLLER_IP=xxx.xxx.xxx.xxx
```

Start with both compose files:

```sh
docker compose -f docker-compose.yml -f docker-compose.unraid-static-ip.example.yml up -d
```

Then use the static IP for the web UI and Plex webhook.

## Build locally from source

Use this if you want Unraid to build the image instead of pulling from Docker Hub:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```
