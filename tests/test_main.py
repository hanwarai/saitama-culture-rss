import datetime
import pathlib
from typing import Any
from unittest.mock import patch

import pytest

import main


@pytest.fixture
def show_full() -> dict[str, Any]:
    return {
        "show_group_id": "bc260501",
        "show_group_main_title": "第3回トランペット音楽の魅力",
        "show_group_sub_title": "トランペット音楽の魅力",
        "show_term": "2026/5/1(金) 18:30",
        "disp_sort": "202605011830",
        "genre_nm": "音楽",
        "sub_genre_nm": "クラシック",
        "hall_nm": "さいたま市文化センター",
        "sales_list": [
            {
                "sales_term": "2026/3/13(金) 10:00　〜　2026/4/30(木) 23:59",
                "show_sales_status": "空席あり○",
            }
        ],
    }


def test_parse_disp_sort_returns_utc() -> None:
    dt = main.parse_disp_sort("202605011830")
    assert dt.tzinfo == datetime.UTC
    # 2026/5/1 18:30 JST == 2026/5/1 09:30 UTC
    assert dt == datetime.datetime(2026, 5, 1, 9, 30, tzinfo=datetime.UTC)


def test_parse_disp_sort_rejects_bad_format() -> None:
    with pytest.raises(ValueError):
        main.parse_disp_sort("not-a-date")


def test_build_title_combines_main_and_sub_when_different() -> None:
    show = {
        "show_group_main_title": "メイン",
        "show_group_sub_title": "サブ",
    }
    assert main.build_title(show) == "メイン - サブ"


def test_build_title_omits_sub_when_equal_to_main() -> None:
    show = {
        "show_group_main_title": "同じ",
        "show_group_sub_title": "同じ",
    }
    assert main.build_title(show) == "同じ"


def test_build_title_falls_back_to_show_group_id() -> None:
    show = {"show_group_id": "bc1"}
    assert main.build_title(show) == "bc1"


def test_build_image_tag_returns_cdn_img_with_escaped_alt() -> None:
    tag = main.build_image_tag(
        {"show_group_id": "bc260501", "show_group_main_title": '"危険" な & タイトル'}
    )
    assert tag is not None
    assert 'src="https://cdn.p-ticket.jp/saitama-culture/event/bc260501/internet_pic0_image"' in tag
    # 二重引用符 / アンパサンドは HTML エスケープされる
    assert "&quot;" in tag
    assert "&amp;" in tag


def test_build_image_tag_returns_none_without_show_group_id() -> None:
    assert main.build_image_tag({"show_group_main_title": "no id"}) is None


def test_build_description_includes_image_and_meta(show_full: dict[str, Any]) -> None:
    desc = main.build_description(show_full)
    assert (
        '<img src="https://cdn.p-ticket.jp/saitama-culture/event/bc260501/internet_pic0_image"'
        in desc
    )
    assert "公演日時: 2026/5/1(金) 18:30" in desc
    assert "会場: さいたま市文化センター" in desc
    assert "ジャンル: 音楽 / クラシック" in desc
    assert "販売: 空席あり○" in desc


def test_build_description_drops_list_explanation_for_brevity() -> None:
    desc = main.build_description({"show_group_id": "bc1", "list_explanation": "長い本文"})
    assert "長い本文" not in desc
    # show_group_id だけ与えても画像タグは入る
    assert "<img" in desc


def test_build_description_skips_sales_without_status() -> None:
    desc = main.build_description(
        {
            "show_group_id": "bc1",
            "sales_list": [
                {"sales_term": "2026/3/13"},  # status なし → スキップ
                {"show_sales_status": "完売"},  # status のみ → 採用
            ],
        }
    )
    assert "販売: 完売" in desc
    assert "2026/3/13" not in desc


def test_show_to_item_links_to_detail_page(show_full: dict[str, Any]) -> None:
    item = main.show_to_item(show_full)
    assert item["unique_id"] == "bc260501"
    assert item["link"] == "https://p-ticket.jp/saitama-culture/event/bc260501"
    assert isinstance(item["pubdate"], datetime.datetime)
    assert item["pubdate"].tzinfo == datetime.UTC


def test_build_feed_skips_invalid_shows(show_full: dict[str, Any]) -> None:
    broken = {"show_group_id": "broken", "disp_sort": "garbage"}
    feed = main.build_feed([show_full, broken])
    # feedgenerator は items 属性に list を保持
    assert len(feed.items) == 1
    assert feed.items[0]["unique_id"] == "bc260501"


def test_fetch_show_list_unwraps_payload(show_full: dict[str, Any]) -> None:
    fake_payload = {"status": "success", "data": {"show_list": [show_full]}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return fake_payload

    with patch("main.requests.get", return_value=FakeResponse()) as mock_get:
        shows = main.fetch_show_list()

    assert shows == [show_full]
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["client_id"] == "saitama-culture"
    assert kwargs["params"]["member_kb_no"] == 0
    assert kwargs["timeout"] == main.TIMEOUT


def test_fetch_show_list_raises_on_failure_status() -> None:
    fake_payload = {"status": "fail", "data": {}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return fake_payload

    with (
        patch("main.requests.get", return_value=FakeResponse()),
        pytest.raises(RuntimeError, match="unexpected payload status"),
    ):
        main.fetch_show_list()


def test_fetch_show_list_rejects_non_list_show_list() -> None:
    fake_payload = {"status": "success", "data": {"show_list": "oops"}}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return fake_payload

    with (
        patch("main.requests.get", return_value=FakeResponse()),
        pytest.raises(RuntimeError, match="unexpected show_list type"),
    ):
        main.fetch_show_list()


def test_main_writes_feed_xml(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    show_full: dict[str, Any],
) -> None:
    output = tmp_path / "dist" / "feed.xml"
    monkeypatch.setattr(main, "OUTPUT_PATH", output)
    monkeypatch.setattr(main, "fetch_show_list", lambda: [show_full])

    main.main()

    body = output.read_text(encoding="utf-8")
    assert body.startswith("<?xml")
    assert "bc260501" in body
    assert "https://p-ticket.jp/saitama-culture/event/bc260501" in body
