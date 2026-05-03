"""Text metadata formatter."""
from typing import Any, Dict, List


def _get_bool(cfg: Any, key: str, default: bool) -> bool:
    return bool(getattr(cfg, key, default))


def _get_int(cfg: Any, key: str, default: int) -> int:
    try:
        return int(getattr(cfg, key, default))
    except (TypeError, ValueError):
        return default


def _get_platform(metadata: Dict[str, Any]) -> str:
    return str(
        metadata.get("platform")
        or metadata.get("parser_name")
        or metadata.get("source")
        or ""
    ).lower()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _truncate(text: str, max_length: int) -> str:
    text = _clean(text)
    if not text:
        return ""
    if max_length > 0 and len(text) > max_length:
        return text[:max_length].rstrip() + "..."
    return text


def _is_redundant_twitter_title(
    title: str,
    metadata: Dict[str, Any],
) -> bool:
    title = _clean(title)
    if not title.endswith(" 的推文"):
        return False

    platform = _get_platform(metadata)
    url = _clean(metadata.get("url") or metadata.get("original_url")).lower()
    return (
        "twitter" in platform
        or platform == "x"
        or "x.com" in url
        or "twitter.com" in url
    )


def _format_video_size(metadata: Dict[str, Any]) -> str:
    for key in ("video_size", "size"):
        value = _clean(metadata.get(key))
        if value:
            return value

    video_count = metadata.get("video_count", 0)
    try:
        video_count = int(video_count or 0)
    except (TypeError, ValueError):
        video_count = 0
    if video_count <= 0:
        return ""

    actual_max = metadata.get("max_video_size_mb")
    total = metadata.get("total_video_size_mb", 0.0)
    if actual_max is None:
        return ""

    try:
        actual_max = float(actual_max)
        total = float(total or 0.0)
    except (TypeError, ValueError):
        return ""

    if video_count == 1:
        return f"{actual_max:.1f} MB"
    return f"最大 {actual_max:.1f} MB (共 {video_count} 个视频, 总计 {total:.1f} MB)"


def format_metadata_text(metadata: Dict[str, Any], cfg: Any) -> str:
    """Format user-facing metadata text according to configured field flags."""
    title = _clean(metadata.get("title"))
    author = _clean(metadata.get("author"))
    desc = _clean(metadata.get("desc") or metadata.get("description"))
    timestamp = _clean(
        metadata.get("timestamp")
        or metadata.get("publish_time")
        or metadata.get("created_at")
    )
    video_size = _format_video_size(metadata)
    url = _clean(metadata.get("url") or metadata.get("original_url"))

    if (
        _get_bool(cfg, "hide_redundant_twitter_title", True)
        and _is_redundant_twitter_title(title, metadata)
    ):
        title = ""

    if (
        _get_bool(cfg, "hide_duplicate_title_author", True)
        and title
        and author
        and title == author
    ):
        title = ""

    desc = _truncate(desc, _get_int(cfg, "max_desc_length", 0))

    lines: List[str] = []
    if _get_bool(cfg, "show_title", True) and title:
        lines.append(f"标题：{title}")
    if _get_bool(cfg, "show_author", True) and author:
        lines.append(f"作者：{author}")
    if _get_bool(cfg, "show_desc", True) and desc:
        lines.append(f"简介：{desc}")
    if _get_bool(cfg, "show_timestamp", False) and timestamp:
        lines.append(f"发布时间：{timestamp}")
    if _get_bool(cfg, "show_video_size", False) and video_size:
        lines.append(f"视频大小：{video_size}")
    if _get_bool(cfg, "show_original_url", False) and url:
        lines.append(f"原始链接：{url}")

    return "\n".join(lines).strip()
