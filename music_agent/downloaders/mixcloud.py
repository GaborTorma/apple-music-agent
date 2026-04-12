from music_agent.downloaders import BaseDownloader


class MixcloudDownloader(BaseDownloader):
    """Mixcloud downloader with platform-specific metadata mapping."""

    def _parse_metadata(self, meta: dict) -> tuple[str, str, float]:
        title = meta.get("title", "Unknown")
        artist = meta.get("uploader", "Unknown")
        duration = float(meta.get("duration", 0))
        return title, artist, duration
