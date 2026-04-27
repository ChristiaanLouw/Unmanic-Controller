# Unraid Install

## Default bridge install

Use this when port mappings are enough:

```sh
cd /mnt/user/appdata
git clone https://github.com/YOUR-USER/Unmanic-Controller.git
cd Unmanic-Controller
cp .env.example .env
cp Container/settings.example.json Container/settings.json
docker compose up -d --build
```

Once the Docker Hub image is published, use this instead:

```sh
docker compose pull
docker compose up -d
```

If Unraid does not show the WebUI menu or icon after an update, recreate the container from the compose file so Unraid picks up the updated labels:

```sh
docker compose up -d --force-recreate
```

Open the web UI on:

```text
http://YOUR_UNRAID_SERVER_IP:8080
```

Add this Plex webhook URL:

```text
http://YOUR_UNRAID_SERVER_IP:9777
```

## Optional custom network with static IP

Use this only when you want the controller to have its own LAN IP on an existing Unraid custom Docker network.

Add these lines to `.env`:

```env
UNRAID_DOCKER_NETWORK=br2
UNMANIC_CONTROLLER_IP=192.168.6.91
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
