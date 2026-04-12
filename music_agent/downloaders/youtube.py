from music_agent.downloaders import BaseDownloader


class YouTubeDownloader(BaseDownloader):
    """YouTube downloader with platform-specific metadata mapping."""

    def _parse_metadata(self, meta: dict) -> tuple[str, str, float]:
        title = meta.get("title", "Unknown")
        artist = meta.get("channel", meta.get("uploader", "Unknown"))
        duration = float(meta.get("duration", 0))
        return title, artist, duration
