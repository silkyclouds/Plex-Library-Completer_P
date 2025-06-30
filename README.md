# Plex Sync & Completer

![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python)
![Docker](https://img.shields.io/badge/Docker-20.10-blue?style=for-the-badge&logo=docker)
![Plex](https://img.shields.io/badge/Plex-Media%20Server-orange?style=for-the-badge&logo=plex)
![Gemini](https://img.shields.io/badge/Google%20Gemini-AI%20Playlists-purple?style=for-the-badge&logo=google)

A Python script, executed via Docker, to keep Plex music playlists synchronized with streaming services like Spotify and Deezer. Includes advanced features such as weekly AI playlist creation with Google Gemini and automatic download of missing tracks via `streamrip`.

## ✨ Key Features

- **Multi-Platform Synchronization**: Synchronizes public playlists from **Spotify** and **Deezer** directly into your Plex library.
- **Multi-User Management**: Supports synchronization for multiple Plex users, each with their own playlists and configurations.
- **Weekly AI Playlists**: Uses the **Google Gemini** API to analyze a user's taste (based on a "favorites" playlist) and generate a new personalized playlist every week.
- **Automatic Completion**: Identifies playlist tracks that are missing from your Plex library.
- **Automatic Download**: Uses **`streamrip`** to automatically search and download albums containing missing tracks from Deezer, effectively completing your library.
- **Scheduled Cleanup**: Automatically removes old playlists to keep the library organized.
- **Background Execution**: Designed to run 24/7 in a Docker container, with customizable synchronization cycles.
- **Fast Statistics**: Charts are generated from the favorite tracks playlist, speeding up processing even on very large libraries.
- **Multilingual Interface**: Full bilingual support (English/Italian) with automatic language detection and seamless switching.

## 🌐 Internationalization

The application features a complete bilingual interface supporting both **English** and **Italian** languages:

### Language Features
- **Automatic Detection**: The interface automatically detects the user's preferred language from browser settings
- **Manual Switching**: Users can manually switch between languages using the language selector
- **Complete Translation**: All interface elements are translated including:
  - Dashboard and navigation menus
  - Chart labels and statistics
  - AI assistant messages and prompts
  - Error messages and notifications
  - Form placeholders and buttons

### How Language Switching Works
- **Session-Based**: Language preference is stored in the user's session
- **Dynamic Charts**: All statistical charts (genre distribution, artist rankings, etc.) update their labels based on the selected language
- **AI Integration**: The AI assistant adapts its responses and suggestions to the selected language
- **Real-Time**: Language changes take effect immediately without requiring a page refresh

The language system is powered by a custom i18n service with JSON-based translation files located in `plex_playlist_sync/translations/`.

## 🚀 Getting Started

### Prerequisites

-   [Docker](https://www.docker.com/products/docker-desktop/) and Docker Compose installed.
-   A Plex server with administrative access.
-   A [Deezer](https://www.deezer.com) account (to obtain the ARL).
-   A [Spotify for Developers](https://developer.spotify.com/dashboard) account (for API credentials).
-   A [Google AI Studio](https://aistudio.google.com/) account (for Gemini API key).

### ⚙️ Installation and Configuration

1.  **Clone the Repository**
    (Once published on GitHub)
    ```bash
    git clone <YOUR_PRIVATE_REPOSITORY_URL>
    cd Plex-Library-Completer
    ```

2.  **Create the `.env` file**
    Copy the example file `.env.example` in the project root and rename it to `.env`.
    ```bash
    cp .env.example .env
    ```
    Then open the `.env` file and enter all your personal values.

3.  **Create the `config.toml` file**
    This file is for `streamrip` configuration. Copy `config.example.toml` and rename it to `config.toml`.
    ```bash
    cp config.example.toml config.toml
    ```
    Open `config.toml` and enter your Deezer ARL.

4.  **Verify Volume Paths**
    Open the `docker-compose.yml` file and make sure the path to your music library is correct. Replace `M:\Organizzata` with the actual path on your PC.
    ```yaml
    volumes:
      - M:\Organizzata:/music # <-- Modify this path
      # ... other volumes
    ```

### ▶️ Execution

To start the container in the background:
```bash
docker-compose up -d --build
```
The `--build` flag is recommended the first time or after code changes.

To view logs in real time:
```bash
docker-compose logs -f
```

To stop the container:
```bash
docker-compose down
```

## Environment Variables (`.env`)

This is the complete list of variables to configure in the `.env` file.

| Variable                       | Description                                                                                              | Example                                       |
| ------------------------------- | -------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| `PLEX_URL`                      | URL of your Plex server.                                                                                | `http://192.168.1.10:32400`                   |
| `PLEX_TOKEN`                    | Access token for the main Plex user.                                                                    | `yourPlexTokenHere`                           |
| `PLEX_TOKEN_USERS`              | Access token for the secondary Plex user (optional).                                                    | `secondaryUserPlexToken`                      |
| `LIBRARY_NAME`                  | Exact name of your music library on Plex.                                                               | `Music`                                       |
| `DEEZER_PLAYLIST_ID`            | Numeric IDs of Deezer playlists to sync for the main user, comma-separated.                           | `12345678,87654321`                           |
| `DEEZER_PLAYLIST_ID_SECONDARY`  | Deezer playlist IDs for the secondary user, comma-separated (optional).                               | `98765432`                                    |
| `SPOTIFY_CLIENT_ID`             | Client ID obtained from Spotify for Developers dashboard.                                              | `yourSpotifyClientID`                         |
| `SPOTIFY_CLIENT_SECRET`         | Client Secret obtained from Spotify for Developers dashboard.                                          | `yourSpotifyClientSecret`                     |
| `GEMINI_API_KEY`                | API key obtained from Google AI Studio for AI functions.                                              | `yourGeminiApiKey`                            |
| `PLEX_FAVORITES_PLAYLIST_ID_MAIN` | Rating Key (numeric ID) of the "favorites" Plex playlist for the main user (for AI).                 | `12345`                                       |
| `PLEX_FAVORITES_PLAYLIST_ID_SECONDARY` | Rating Key of the "favorites" playlist for the secondary user (optional, for AI).                   | `54321`                                       |
| `SECONDS_TO_WAIT`               | Seconds to wait between synchronization cycles.                                                        | `86400` (24 hours)                            |
| `WEEKS_LIMIT`                   | Number of weeks after which old playlists are deleted.                                                 | `4`                                           |
| `PRESERVE_TAG`                  | If this text is in a playlist title, it will not be deleted.                                          | `NO_DELETE`                                   |
| `FORCE_DELETE_OLD_PLAYLISTS`    | Set to `1` to enable automatic deletion of old playlists.                                             | `0` (disabled)                                |
| `RUN_DOWNLOADER`                | Set to `1` to enable automatic download of missing tracks.                                            | `1` (enabled)                                 |
| `RUN_GEMINI_PLAYLIST_CREATION`  | Set to `1` to enable weekly AI playlist creation.                                                     | `1` (enabled)                                 |

## Project Structure

```
Plex-Library-Completer/
├── .env                  # Your secret environment variables
├── .gitignore            # Files and folders to ignore for Git
├── config.toml           # Streamrip configuration (e.g. ARL)
├── docker-compose.yml    # Docker orchestration file
├── Dockerfile            # Instructions to build the image
├── README.md             # This file
├── requirements.txt      # Python dependencies
│
└── plex_playlist_sync/   # Application source code
    ├── run.py
    └── utils/
        ├── cleanup.py
        ├── deezer.py
        ├── downloader.py
        └── ...
```
## Example Images
![alt text](index.png)
![alt text](missing_tracks.png)
![alt text](stats.png)
![alt text](ai_lab.png)