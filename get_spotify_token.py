import os
import base64
import urllib.parse
import webbrowser
import urllib.request
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
# We use a standard secure URL to bypass Spotify's strict localhost checks
REDIRECT_URI = "https://google.com/callback"
SCOPE = "user-read-currently-playing user-read-recently-played user-top-read"

if not CLIENT_ID or not CLIENT_SECRET:
    print("❌ ERROR: SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET must be set in your .env file.")
    exit(1)

def get_refresh_token():
    print("="*60)
    print("🎵 SPOTIFY AUTHENTICATION 🎵")
    print("="*60)
    
    # 1. Generate auth URL
    auth_url = f"https://accounts.spotify.com/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={urllib.parse.quote(REDIRECT_URI)}&scope={urllib.parse.quote(SCOPE)}"
    
    print("\n1. Opening your browser to authorize...")
    print(f"If it doesn't open automatically, click this link:\n\n{auth_url}\n")
    webbrowser.open(auth_url)

    # 2. Get the redirected URL from the user
    print("2. Log in and click 'Agree'.")
    print("3. You will be redirected to a Google page (it might say 'Not Found', that's OK!).")
    print("4. Look at the URL bar in your browser. It should look like:")
    print("   https://google.com/callback?code=NApCCg...\n")
    
    redirected_url = input("👉 PASTE THE ENTIRE REDIRECTED URL HERE: ").strip()
    
    if not redirected_url:
        print("❌ No URL provided.")
        return

    # Extract the code
    try:
        query = urllib.parse.urlparse(redirected_url).query
        params = urllib.parse.parse_qs(query)
        auth_code = params["code"][0]
    except Exception as e:
        print("❌ Could not find the 'code' in the URL you pasted. Make sure you pasted the full URL.")
        return

    print("\n✅ Got Authorization Code. Exchanging for Refresh Token...")

    # 3. Exchange code for refresh token
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI
    }).encode("utf-8")
    
    req = urllib.request.Request("https://accounts.spotify.com/api/token", data=data)
    req.add_header("Authorization", f"Basic {auth_header}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            refresh_token = res_data.get("refresh_token")
            
            print("\n" + "="*60)
            print("🎉 SUCCESS! Here is your Refresh Token:")
            print("="*60)
            print(f"\n{refresh_token}\n")
            print("="*60)
            print("👉 Copy the token above and add it to your .env file as SPOTIFY_REFRESH_TOKEN")
            
    except urllib.error.HTTPError as e:
        print(f"\n❌ HTTP Error exchanging token: {e.code}")
        print(e.read().decode())
    except Exception as e:
        print(f"\n❌ Error exchanging token: {e}")

if __name__ == "__main__":
    get_refresh_token()
