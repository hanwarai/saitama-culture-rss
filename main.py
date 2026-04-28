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


def build_description(show: dict[str, Any]) -> str:
    parts: list[str] = []
    if show.get("show_term"):
        parts.append(f"公演日時: {show['show_term']}")
    if show.get("hall_nm"):
        parts.append(f"会場: {show['hall_nm']}")
    genre = " / ".join(b for b in (show.get("genre_nm"), show.get("sub_genre_nm")) if b)
    if genre:
        parts.append(f"ジャンル: {genre}")
    for sales in show.get("sales_list") or []:
        if not sales.get("sales_term"):
            continue
        line = f"販売: {sales['sales_term']}"
        if sales.get("show_sales_status"):
            line += f" ({sales['show_sales_status']})"
        parts.append(line)
    explanation = show.get("list_explanation") or ""
    if explanation:
        # ソース側に文字列リテラルの "</br>" が混じっているので <br> に正規化
        parts.append(explanation.replace("</br>", "<br>"))
    return "<br><br>".join(parts)


def show_to_item(show: dict[str, Any]) -> dict[str, Any]:
    show_group_id = show["show_group_id"]
    return {
        "unique_id": show_group_id,
        "title": build_title(show),
        "link": DETAIL_URL_TEMPLATE.format(show_group_id=show_group_id),
        "description": build_description(show),
        "pubdate": parse_disp_sort(show["disp_sort"]),
    }


def build_feed(shows: list[dict[str, Any]]) -> feedgenerator.Atom1Feed:
    feed = feedgenerator.Atom1Feed(
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
