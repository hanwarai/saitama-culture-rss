import datetime
import os
from pathlib import Path
from typing import Any

import feedgenerator
import requests

API_URL = "https://api.p-ticket.jp/show/get-list-home"
CLIENT_ID = "saitama-culture"
SOURCE_URL = f"https://p-ticket.jp/{CLIENT_ID}"
DETAIL_URL_TEMPLATE = f"{SOURCE_URL}/event/{{show_group_id}}"
IMAGE_URL_TEMPLATE = (
    f"https://cdn.p-ticket.jp/{CLIENT_ID}/event/{{show_group_id}}/internet_pic0_image"
)

FEED_TITLE = "p-ticket saitama-culture"
FEED_DESCRIPTION = "p-ticket.jp の saitama-culture (さいたま市文化センター等) の公演一覧"
FEED_LANGUAGE = "ja"

# WAF が Origin/Referer を見ているので、両方付けないと 502 が返る
API_HEADERS = {
    "Origin": "https://p-ticket.jp",
    "Referer": SOURCE_URL,
    "Accept": "application/json, text/plain, */*",
}

JST = datetime.timezone(datetime.timedelta(hours=9))
TIMEOUT = (5, 30)
SSL_VERIFY = os.getenv("SSL_VERIFY", "True") == "True"
RECORD_FETCH_LIMIT = 100

OUTPUT_PATH = Path("dist") / "feed.xml"


def fetch_show_list() -> list[dict[str, Any]]:
    params: dict[str, str | int] = {
        "client_id": CLIENT_ID,
        "start_position": 1,
        "end_position": RECORD_FETCH_LIMIT,
        "member_kb_no": 0,
    }
    response = requests.get(
        API_URL,
        params=params,
        headers=API_HEADERS,
        timeout=TIMEOUT,
        verify=SSL_VERIFY,
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"unexpected payload status: {payload!r}")
    data = payload.get("data") or {}
    shows = data.get("show_list") or []
    if not isinstance(shows, list):
        raise RuntimeError(f"unexpected show_list type: {type(shows).__name__}")
    return shows


def parse_disp_sort(disp_sort: str) -> datetime.datetime:
    """`YYYYMMDDHHMM` (JST) を UTC datetime に変換する."""
    naive = datetime.datetime.strptime(disp_sort, "%Y%m%d%H%M")
    return naive.replace(tzinfo=JST).astimezone(datetime.UTC)


def build_title(show: dict[str, Any]) -> str:
    main = show.get("show_group_main_title") or show.get("show_group_id") or ""
    sub = show.get("show_group_sub_title")
    if sub and sub != main:
        return f"{main} - {sub}"
    return str(main)


def build_image_url(show: dict[str, Any]) -> str | None:
    show_group_id = show.get("show_group_id")
    if not show_group_id:
        return None
    return IMAGE_URL_TEMPLATE.format(show_group_id=show_group_id)


def build_description(show: dict[str, Any]) -> str:
    """要点だけのコンパクトなアイテム本文を組み立てる.

    画像はフィード側で <media:thumbnail> として別途吐くので本文には入れない。
    本文は一目で分かるメタ (公演日時 / 会場 / ジャンル / 販売状況) のみ。
    長文の list_explanation はあえて含めない (情報量過多の元なので)。
    """
    parts: list[str] = []
    if show.get("show_term"):
        parts.append(f"公演日時: {show['show_term']}")
    if show.get("hall_nm"):
        parts.append(f"会場: {show['hall_nm']}")
    genre = " / ".join(b for b in (show.get("genre_nm"), show.get("sub_genre_nm")) if b)
    if genre:
        parts.append(f"ジャンル: {genre}")
    for sales in show.get("sales_list") or []:
        status = sales.get("show_sales_status")
        if status:
            parts.append(f"販売: {status}")
    return "<br>".join(parts)


def show_to_item(show: dict[str, Any]) -> dict[str, Any]:
    show_group_id = show["show_group_id"]
    item: dict[str, Any] = {
        "unique_id": show_group_id,
        "title": build_title(show),
        "link": DETAIL_URL_TEMPLATE.format(show_group_id=show_group_id),
        "description": build_description(show),
        "pubdate": parse_disp_sort(show["disp_sort"]),
    }
    image_url = build_image_url(show)
    if image_url is not None:
        item["media_thumbnail"] = image_url
    return item


class AtomFeedWithMedia(feedgenerator.Atom1Feed):
    """Atom1Feed + Media RSS namespace で `<media:thumbnail>` を出すラッパ."""

    def root_attributes(self) -> dict[str, str]:
        attrs: dict[str, str] = super().root_attributes()
        attrs["xmlns:media"] = "http://search.yahoo.com/mrss/"
        return attrs

    def add_item_elements(self, handler: Any, item: dict[str, Any]) -> None:
        super().add_item_elements(handler, item)
        thumbnail = item.get("media_thumbnail")
        if thumbnail:
            handler.addQuickElement("media:thumbnail", "", {"url": thumbnail})


def build_feed(shows: list[dict[str, Any]]) -> AtomFeedWithMedia:
    feed = AtomFeedWithMedia(
        title=FEED_TITLE,
        link=SOURCE_URL,
        description=FEED_DESCRIPTION,
        language=FEED_LANGUAGE,
    )
    for show in shows:
        try:
            item = show_to_item(show)
        except (KeyError, ValueError) as exc:
            print(f"[ERROR] skipping {show.get('show_group_id')!r}: {exc}")
            continue
        feed.add_item(content="", **item)
    return feed


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    feed = build_feed(fetch_show_list())
    with OUTPUT_PATH.open("w", encoding="utf-8") as fp:
        feed.write(fp, "utf-8")
    print(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
