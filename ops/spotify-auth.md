# Spotify one-time auth (ticket 7)

The poll refreshes its access token on every run from a stored refresh
token. This flow obtains that refresh token once. It contains no values:
substitute your own where placeholders appear.

## Steps

1. Create (or identify) the Spotify app in the developer dashboard.
2. Set the redirect URI to exactly `http://127.0.0.1:8888/callback`.
3. Open the authorize URL (with your client id in place of `CLIENT_ID`):

   ```
   https://accounts.spotify.com/authorize?client_id=CLIENT_ID&response_type=code&redirect_uri=http://127.0.0.1:8888/callback&scope=user-read-recently-played
   ```

4. Approve access. The browser redirects to the callback URL carrying a
   `code` query parameter; copy that code.
5. Exchange the code for tokens:

   ```sh
   curl -s -X POST https://accounts.spotify.com/api/token \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -H "Authorization: Basic REPLACE_WITH_BASE64_OF_YOUR_OWN_CREDENTIALS" \
     -d "grant_type=authorization_code" \
     -d "code=PASTE_CODE_HERE" \
     -d "redirect_uri=http://127.0.0.1:8888/callback"
   ```

   The `Authorization` value is the base64 of your own
   `client_id:client_secret` pair, computed locally at exchange time.

6. Put the three values into a local env file **outside the repo**, for
   example `~/.config/ikigai-loop/spotify.env`, and source it at runtime:

   ```
   SPOTIFY_CLIENT_ID=
   SPOTIFY_CLIENT_SECRET=
   SPOTIFY_REFRESH_TOKEN=
   ```

   Never commit that file.

## Runtime behaviour

Each poll POSTs `grant_type=refresh_token` to the token endpoint and keeps
the access token in a poll-local variable only. Any rotated `refresh_token`
in the token response is ignored: the stored refresh token stays
authoritative. If polls start failing with
`spotify: refresh failed (status ...)`, re-run this flow.
