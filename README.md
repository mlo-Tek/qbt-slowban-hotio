# qbt-slowban for hotio/qbittorrent on Unraid

> [!WARNING]
> ⚠️ **AI-assisted project**
>
> This project, including portions of the Python implementation, Unraid template, and documentation, was created with substantial assistance from **OpenAI ChatGPT** and subsequently reviewed and adapted for the intended setup.
>
> AI-generated or AI-assisted code can contain defects. Review the code and test it in your own environment before relying on it.

A lightweight Python sidecar for **hotio/qbittorrent** on **Unraid**.

This repository is a fork of [`TechClusterHQ/qbt-slowban`](https://github.com/TechClusterHQ/qbt-slowban), adapted from the original LinuxServer.io Docker Mod approach to run as a standalone sidecar container for hotio/qbittorrent.

## Features

- Designed as a separate sidecar container for hotio/qbittorrent
- Uses the qBittorrent Web API
- Tracks slow peers per torrent
- Warning before a ban is applied
- Persistent state across container restarts
- Scheduled clearing of the qBittorrent manual ban list
- Optional permanent bans that survive scheduled clears
- Dry-run mode
- 2-hour rotating log files
- Configurable log retention
- Periodic status summaries
- Colored console output

## Default settings

| Setting | Default |
|---|---:|
| Warning after | 45 seconds |
| Ban after | 90 seconds |
| Minimum upload speed | 50,768 B/s |
| Poll interval | 10 seconds |
| Summary interval | 600 seconds |
| Clear manual bans | Every 12 hours |
| Log retention | 7 days |
| Dry run | false |

The minimum upload-speed value is expressed in **bytes per second**.

## Repository layout

```text
qbt-slowban-hotio/
├── slowban.py
├── my-qbt-slowban.xml
├── README.md
├── SECURITY.md
└── .gitignore
```

## Unraid installation

### Option 1: Download directly from GitHub

Create the appdata directories:

```bash
mkdir -p /mnt/cache/appdata/qbt-slowban/{state,logs}
```

Download the Python script directly into the appdata directory:

```bash
curl -L   https://raw.githubusercontent.com/mlo-Tek/qbt-slowban-hotio/main/slowban.py   -o /mnt/cache/appdata/qbt-slowban/slowban.py
```

Download the Unraid template directly into the user-template directory:

```bash
curl -L   https://raw.githubusercontent.com/mlo-Tek/qbt-slowban-hotio/main/my-qbt-slowban.xml   -o /boot/config/plugins/dockerMan/templates-user/my-qbt-slowban.xml
```

Then open the Unraid Docker page, choose **Add Container**, and select the `qbt-slowban` template.

Set at minimum:

- `QBT_URL`
- `QBT_USERNAME`
- `QBT_PASSWORD`

Adjust the Docker network if needed. The public template uses `bridge` by default because custom VLAN names and fixed IP addresses are installation-specific.

Start the container and inspect its log.

### Option 2: Manual installation

1. Create the appdata directories:

   ```bash
   mkdir -p /mnt/cache/appdata/qbt-slowban/{state,logs}
   ```

2. Copy `slowban.py` to:

   ```text
   /mnt/cache/appdata/qbt-slowban/slowban.py
   ```

3. Copy `my-qbt-slowban.xml` to:

   ```text
   /boot/config/plugins/dockerMan/templates-user/my-qbt-slowban.xml
   ```

4. In the Unraid Docker page, choose **Add Container** and select the `qbt-slowban` template.

5. Set at minimum:

   - `QBT_URL`
   - `QBT_USERNAME`
   - `QBT_PASSWORD`

6. Adjust the Docker network if needed.

7. Start the container and inspect its log.

## Important configuration variables

### qBittorrent

- `QBT_URL` — qBittorrent WebUI/API URL
- `QBT_USERNAME` — qBittorrent username
- `QBT_PASSWORD` — qBittorrent password

### Slow-peer detection

- `SLOWBAN_MIN_SPEED` — minimum upload speed in bytes per second
- `SLOWBAN_WARN_TIME` — seconds below the threshold before a warning is logged
- `SLOWBAN_THRESHOLD_TIME` — seconds below the threshold before the peer is banned
- `SLOWBAN_POLL_INTERVAL` — polling interval in seconds

`SLOWBAN_WARN_TIME` must be lower than `SLOWBAN_THRESHOLD_TIME`.

### Scheduled unban

`SLOWBAN_CLEAR_PERIODICALLY` accepts a 5-field cron expression.

Default:

```text
0 */12 * * *
```

This runs at 00:00 and 12:00 according to the configured container timezone.

`SLOWBAN_BANNED_PEERS` can contain comma-separated peers that should be kept permanently banned when the scheduled clear runs.

### Logging

- `SLOWBAN_LOG_LEVEL`
- `SLOWBAN_LOG_DIR`
- `SLOWBAN_LOG_RETENTION_DAYS`
- `SLOWBAN_LOG_UNBAN_DETAILS`
- `SLOWBAN_COLOR_LOGS`
- `SLOWBAN_SUMMARY_INTERVAL`

Log files are split into 2-hour time slots.

## Security

Do **not** commit a populated Unraid XML template containing your real qBittorrent username, password, internal IP addresses, or other private configuration.

The template included in this repository intentionally contains only generic example values for qBittorrent connectivity.

See [`SECURITY.md`](SECURITY.md) for additional notes.

## AI disclosure

This project, including portions of the Python implementation, Unraid template, and documentation, was created with substantial assistance from **OpenAI ChatGPT** and subsequently reviewed and adapted for the intended setup.

AI-generated or AI-assisted code can contain defects. Review the code and test it in your own environment before relying on it.

## Disclaimer

Use at your own risk. Banning peers and manipulating the qBittorrent manual ban list can affect active transfers and connectivity. Test with `SLOWBAN_DRY_RUN=true` first if you want to verify behavior without applying real bans.
