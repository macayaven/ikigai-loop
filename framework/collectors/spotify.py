"""Spotify recently-played collector with a per-poll refresh (ticket 7). Off the card path: Spotify's Developer Policy (§III.14) doesn't allow ingesting Spotify Content into an AI model."""

import base64
import json
import os
import urllib.error
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from framework.collectors.common import (
    CollectorError,
    HttpGet,
    HttpPost,
    as_dict,
    as_list,
    event_id,
    subject_id_from_env,
    urllib_http_get,
    urllib_http_post,
)
from framework.schemas import Event, MusicPlayData

TOKEN_URL = "https://accounts.spotify.com/api/token"
RECENTLY_PLAYED_BASE = "https://api.spotify.com/v1/me/player/recently-played?limit=50"


def _parse_played_at(value: object) -> datetime | None:
    """Parse a Spotify played_at timestamp, or None when unusable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed


def _epoch_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


class SpotifyCollector:
    """Poll recently-played tracks; the access token is refreshed every poll."""

    def __init__(
        self,
        http_get: HttpGet = urllib_http_get,
        http_post: HttpPost = urllib_http_post,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http_get = http_get
        self._http_post = http_post
        self._now_fn = now_fn
        self.name = "spotify"
        self.version = "spotify@0.1.0"

    def poll(self, cursor: Any) -> tuple[list[Event], Any]:
        now = self._now_fn()
        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        if not client_id:
            raise CollectorError("spotify: SPOTIFY_CLIENT_ID is not set")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        if not client_secret:
            raise CollectorError("spotify: SPOTIFY_CLIENT_SECRET is not set")
        refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN")
        if not refresh_token:
            raise CollectorError("spotify: SPOTIFY_REFRESH_TOKEN is not set")
        access_token = self._refresh(client_id, client_secret, refresh_token)
        subject_id = subject_id_from_env()

        after_ms: int | None = None
        cursor_dict = as_dict(cursor)
        if cursor_dict is not None:
            raw_after = cursor_dict.get("after_ms")
            if isinstance(raw_after, int) and not isinstance(raw_after, bool):
                after_ms = raw_after

        url = RECENTLY_PLAYED_BASE
        if after_ms is not None:
            url += f"&after={after_ms}"
        try:
            response = self._http_get(
                url,
                {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
            )
        except CollectorError:
            raise CollectorError("spotify: network error") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CollectorError("spotify: network error") from None
        if response.status != 200:
            raise CollectorError(
                f"spotify: fetch failed (status {response.status})"
            ) from None
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CollectorError("spotify: invalid response") from None
        payload_dict = as_dict(payload)
        items = as_list(payload_dict.get("items")) if payload_dict else None
        if items is None:
            raise CollectorError("spotify: invalid response") from None

        plays: list[tuple[int, str, str, str, datetime]] = []
        for item in items:
            parsed = self._parse_item(item, after_ms)
            if parsed is not None:
                plays.append(parsed)
        plays.sort(key=lambda play: play[0])

        events: list[Event] = []
        for _, track_id, track_name, artist, played_at in plays:
            played_utc = played_at.astimezone(UTC)
            source_id = f"{track_id}@{played_utc.isoformat()}"
            events.append(
                Event(
                    id=event_id("spotify", source_id),
                    subject_id=subject_id,
                    source="spotify",
                    type="music.play",
                    time=played_at,
                    source_id=source_id,
                    data=MusicPlayData(
                        track=track_name, artist=artist, played_at=played_at
                    ),
                    tier="private",
                    collected_at=now,
                    collector_version=self.version,
                )
            )
        new_after = after_ms
        if plays:
            new_after = max(play[0] for play in plays)
        return events, {"after_ms": new_after}

    def _refresh(self, client_id: str, client_secret: str, refresh_token: str) -> str:
        """Exchange the stored refresh token for a poll-local access token."""
        auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        form = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        ).encode()
        try:
            response = self._http_post(
                TOKEN_URL,
                {
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                form,
            )
        except CollectorError:
            raise CollectorError("spotify: network error") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CollectorError("spotify: network error") from None
        if response.status != 200:
            raise CollectorError(
                f"spotify: refresh failed (status {response.status})"
            ) from None
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CollectorError("spotify: invalid response") from None
        payload_dict = as_dict(payload)
        token = payload_dict.get("access_token") if payload_dict else None
        if not isinstance(token, str) or not token:
            raise CollectorError("spotify: invalid response") from None
        return token

    def _parse_item(
        self, item: Any, after_ms: int | None
    ) -> tuple[int, str, str, str, datetime] | None:
        """Map one recently-played entry, or None when it carries no signal."""
        item_dict = as_dict(item)
        if item_dict is None:
            return None
        track = as_dict(item_dict.get("track"))
        if track is None:
            return None
        track_id = track.get("id")
        track_name = track.get("name")
        if not isinstance(track_id, str) or not track_id:
            return None
        if not isinstance(track_name, str) or not track_name:
            return None
        artists = as_list(track.get("artists"))
        artist = ""
        if artists:
            first = as_dict(artists[0])
            if first is not None:
                raw_artist = first.get("name")
                if isinstance(raw_artist, str) and raw_artist:
                    artist = raw_artist
        if not artist:
            return None
        played_at = _parse_played_at(item_dict.get("played_at"))
        if played_at is None:
            return None
        played_ms = _epoch_ms(played_at)
        if after_ms is not None and played_ms <= after_ms:
            return None
        return (played_ms, track_id, track_name, artist, played_at)
