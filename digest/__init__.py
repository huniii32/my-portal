"""Daily work-digest collector package (local-only, bounded)."""

from digest.collector import generate_digest, load_digest, parse_day

__all__ = ["generate_digest", "load_digest", "parse_day"]
