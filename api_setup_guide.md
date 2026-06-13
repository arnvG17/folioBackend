# Tool Integrations & API Setup Guide

## How the Tools Work

When a user asks a question, the Smart Agent follows this flow:

1.  **Routing**: The `router.py` script checks the query for keywords. If it sees "spotify", "listening", "youtube", "github", etc., it flags that specific tools are needed.
2.  **Parallel Execution**: The `agent.py` orchestrator takes those flags and runs the required tools *at the same time* (in parallel) to save time.
3.  **Data Fetching**:
    *   **Spotify**: Hits the Spotify Web API to check what you are currently listening to, or your recently played tracks. (Cached for 30s).
    *   **YouTube**: Hits the YouTube Data API v3 to fetch the latest videos uploaded to your channel. (Cached for 5m).
    *   **GitHub**: Hits the GitHub REST API to fetch your recent public events (pushes, stars, PRs) and your top repositories. (Cached for 2m).
4.  **Context Injection**: The raw JSON data from these APIs is converted into a readable string (e.g., "🎵 SPOTIFY — Currently Playing: Not Like Us by Kendrick Lamar") and injected invisibly into the prompt alongside your `me.txt` knowledge.
5.  **Generation**: The LLM reads all this context and generates a natural response.

---

## Getting Your API Keys

You need to add these keys to the `.env` file in your `ragfolio-backend` folder.

### 1. Spotify Setup

Spotify is the most complex because it requires OAuth. You need a Client ID, a Client Secret, and a Refresh Token (so the backend can keep getting new access tokens without you logging in).

**Links:**
*   Developer Dashboard: [https://developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)

**Steps:**
1.  Go to the Developer Dashboard and log in.
2.  Click **Create App**.
    *   App Name: `Portfolio Agent`
    *   App Description: `Fetching now playing data`
    *   Redirect URI: `http://localhost:8080/callback` (We just need this temporarily).
    *   Web API: Check the box.
3.  Once created, click **Settings**. Here you will find your `Client ID` and `Client Secret`.
4.  **Getting the Refresh Token:**
    *   Because you only need to authenticate *yourself*, the easiest way is to use a quick script. Since we don't have a frontend flow built for this yet, here is how to do it manually.
    *   Open your browser and go to this URL (replace `YOUR_CLIENT_ID` with your actual Client ID):
        `https://accounts.spotify.com/authorize?client_id=YOUR_CLIENT_ID&response_type=code&redirect_uri=http://localhost:8080/callback&scope=user-read-currently-playing%20user-read-recently-played`
    *   Click "Agree".
    *   You will be redirected to `localhost:8080`. Look at the URL bar. It will look like `http://localhost:8080/callback?code=NApCCg...`.
    *   Copy everything after `code=`. This is your **Authorization Code**.
    *   Now, you need to exchange this code for a refresh token. Open a terminal and run this `curl` command (replace placeholders):
        ```bash
        curl -H "Authorization: Basic BASE64_ENCODED(client_id:client_secret)" -d grant_type=authorization_code -d code=YOUR_AUTH_CODE -d redirect_uri=http://localhost:8080/callback https://accounts.spotify.com/api/token
        ```
        *(Note: Generating that base64 string or running the curl can be annoying. If you want, I can write a quick python script in your backend folder `get_spotify_token.py` that automates this step for you. Just let me know!)*

**.env variables needed:**
*   `SPOTIFY_CLIENT_ID`
*   `SPOTIFY_CLIENT_SECRET`
*   `SPOTIFY_REFRESH_TOKEN`

---

### 2. YouTube Setup

YouTube uses a simple API key, but you must enable the specific API in Google Cloud.

**Links:**
*   Google Cloud Console: [https://console.cloud.google.com/](https://console.cloud.google.com/)

**Steps:**
1.  Go to the Google Cloud Console and create a new project (or use an existing one).
2.  Go to **APIs & Services > Library**.
3.  Search for **YouTube Data API v3** and click **Enable**.
4.  Go to **APIs & Services > Credentials**.
5.  Click **Create Credentials > API Key**.
6.  Copy the generated API Key.
7.  **Finding your Channel ID:**
    *   Go to your YouTube channel page.
    *   If the URL looks like `youtube.com/channel/UC...`, the part starting with `UC` is your Channel ID.
    *   If it has a handle (`youtube.com/@arnav`), you can find your Channel ID in YouTube Studio -> Settings -> Channel -> Advanced Settings -> Manage YouTube Account -> View Advanced Settings.

**.env variables needed:**
*   `YOUTUBE_API_KEY`
*   `YOUTUBE_CHANNEL_ID`

---

### 3. GitHub Setup

GitHub is the easiest. The API works without auth, but rate limits are very strict. A personal access token increases the limit.

**Links:**
*   GitHub Tokens: [https://github.com/settings/tokens](https://github.com/settings/tokens)

**Steps:**
1.  Go to GitHub Settings -> Developer Settings -> Personal Access Tokens -> Tokens (classic).
2.  Click **Generate new token (classic)**.
3.  Give it a note (e.g., "Portfolio Agent").
4.  Expiration: Set to "No expiration" (or whatever you prefer).
5.  Select scopes: Check `public_repo` and `read:user`.
6.  Click **Generate token**.
7.  Copy the token (it starts with `ghp_`).

**.env variables needed:**
*   `GITHUB_TOKEN`
*   `GITHUB_USERNAME` (Just your username, e.g., `arnvG17`)
