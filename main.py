from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import requests
import os
from datetime import datetime, timedelta, timezone

# ====================== 設定 ======================
JST = timezone(timedelta(hours=9))
today = datetime.now(JST)
TARGET_DATE = today.strftime("%Y%m%d")
weekday = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]

# 六曜（簡易）
rokuyou_list = ["先勝", "友引", "先負", "仏滅", "大安", "赤口"]
rokuyou = rokuyou_list[(today.year * 12 + today.month + today.day) % 6]

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
if not WEBHOOK_URL:
    print("❌ DISCORD_WEBHOOK_URL が設定されていません")
    exit(1)

BLACKLIST = re.compile(
    r"関係者|結婚式|Wedding|ファーム|中地区公式戦|少年野球",
    re.IGNORECASE
)

print("=== 名古屋エリアイベント（イベント＋ドームベータ版） ===\n")
print(f"対象日: {today.strftime('%m月%d日')}（{weekday}） {rokuyou}\n")

events = []
seen = set()


def add_event(time_text, venue, artist):
    time_text = time_text.strip() if time_text else "時間情報なし"
    venue = venue.strip() if venue else ""
    artist = artist.strip() if artist else ""

    if not artist:
        return

    key = f"{time_text}|{venue}|{artist}"
    if key in seen:
        return

    seen.add(key)
    events.append({
        "time": time_text,
        "venue": venue,
        "artist": artist
    })


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ==================== サンデーフォーク ====================
    print("🔍 サンデーフォークを検索中...")

    page.goto(
        f"https://www.sundayfolk.com/calendar/{today.year}/{today.month:02d}/",
        timeout=60000
    )
    page.wait_for_timeout(10000)

    soup = BeautifulSoup(page.content(), "html.parser")

    block = soup.find("div", id=f"d{TARGET_DATE}")
    if block:
        table = block.find("table", class_="tableList")
        if table:
            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) < 5:
                    continue

                artist = cols[0].get_text(" ", strip=True)
                venue = cols[3].get_text(" ", strip=True)
                time_text = cols[2].get_text(" ", strip=True)

                region_icon = cols[4].find("img")
                if not region_icon or region_icon.get("alt") != "名古屋":
                    continue

                if any(x in artist for x in ["中止", "延期", "関係者"]):
                    continue

                if not time_text or len(time_text) < 3:
                    link = cols[1].find("a")
                    if link and link.get("href"):
                        detail_url = "https://www.sundayfolk.com" + link.get("href")

                        page.goto(detail_url, timeout=30000)
                        page.wait_for_timeout(4000)

                        detail_text = BeautifulSoup(
                            page.content(),
                            "html.parser"
                        ).get_text(" ", strip=True)

                        m = re.search(r"(\d{1,2}:\d{2})", detail_text)
                        time_text = m.group(0) if m else "時間情報なし"

                add_event(time_text, venue, artist)

    # ==================== バンテリンドーム ====================
    print("🔍 バンテリンドームを検索中...")

    page.goto(
        "https://www.nagoya-dome.co.jp/sp/eventcalen.php",
        timeout=60000
    )
    page.wait_for_timeout(12000)

    soup = BeautifulSoup(page.content(), "html.parser")

    month = today.month
    day = today.day
    date_regex = re.compile(rf"\b0?{month}/0?{day}\b")

    all_tds = soup.select("td")

    for i, td in enumerate(all_tds):
        day_text = td.get_text(" ", strip=True)

        if not date_regex.search(day_text):
            continue

        title = None

        for next_td in all_tds[i + 1:i + 6]:
            text = " ".join(next_td.get_text(" ", strip=True).split())

            if not text:
                continue

            if date_regex.search(text):
                break

            if "開始" in text or "開場" in text:
                continue

            title = text
            break

        if not title:
            continue

        if "---" in day_text or BLACKLIST.search(title):
            print(f"  └ バンテリン除外: {title}")
            continue

        start_match = re.search(r"開始[\s　／]*(\d{1,2}:\d{2})", day_text)
        if start_match:
            time_text = start_match.group(1)
        else:
            times = re.findall(r"\d{1,2}:\d{2}", day_text)
            time_text = times[-1] if times else "時間情報なし"

        add_event(
            time_text,
            "バンテリンドームナゴヤ",
            title
        )

    # ==================== キョードー東海 ====================
    print("🔍 キョードー東海を検索中...")

    page.goto(
        "https://kyodotokai.co.jp/events/calendor",
        timeout=60000
    )
    page.wait_for_timeout(12000)

    soup = BeautifulSoup(page.content(), "html.parser")

    for strong in soup.find_all("strong"):
        if strong.get_text(strip=True) == str(today.day):
            tr = strong.find_parent("tr")
            if not tr:
                continue

            for link in tr.find_all("a", href=re.compile(r"/events/detail/")):
                artist = link.get("title") or link.get_text(" ", strip=True)
                href = link.get("href")
                if not href:
                    continue

                detail_url = href if href.startswith("http") else "https://kyodotokai.co.jp" + href

                page.goto(detail_url, timeout=30000)
                page.wait_for_timeout(8000)

                detail_soup = BeautifulSoup(page.content(), "html.parser")
                full_text = detail_soup.get_text(" ", strip=True)

                year = today.year
                month = today.month
                day = today.day

                day_block = re.search(
                    rf"{year}年0?{month}月0?{day}日.*?開[　\s]*演\s*(\d{{1,2}}[:：]\d{{2}})",
                    full_text,
                    re.DOTALL
                )
                time_text = day_block.group(1).replace("：", ":") if day_block else "時間情報なし"

                known_venues = [
                    "IGアリーナ",
                    "日本ガイシホール",
                    "クロコくんホール",
                    "Zepp Nagoya",
                    "Niterra日本特殊陶業市民会館フォレストホール",
                    "Niterra日本特殊陶業市民会館ビレッジホール",
                    "愛知県芸術劇場",
                    "御園座",
                    "岡谷鋼機名古屋公会堂",
                    "名古屋市公会堂",
                    "COMTEC PORTBASE",
                    "ポートベース",
                    "DIAMOND HALL",
                    "クラブクワトロ",
                    "NAGOYA JAMMIN",
                ]

                venue = "キョードー東海"
                for v in known_venues:
                    if v in full_text:
                        venue = v
                        break

                nagoya_keywords = [
                    "名古屋", "Zepp", "ポートベース", "IGアリーナ",
                    "ガイシホール", "Niterra", "日本特殊陶業",
                    "中電", "御園座", "クワトロ", "瑞穂",
                    "栄", "NAGOYA JAMMIN", "愛知県芸術劇場"
                ]

                if any(k in venue for k in nagoya_keywords):
                    add_event(time_text, venue, artist)

    browser.close()

# ================== Discord投稿 ==================
events.sort(key=lambda x: x["time"] if ":" in str(x["time"]) else "99:99")

LINE = "─" * 28

message = "**名古屋イベント情報**\n"
message += f"{today.strftime('%m月%d日')}（{weekday}） {rokuyou}\n"
message += "（イベント＋ドームベータ版）\n"
message += LINE + "\n"

if len(events) == 0:
    message += "**本日のイベントはありません**\n"
else:
    message += f"合計 **{len(events)}件**\n"
    message += LINE + "\n\n"

    for e in events:
        message += f"📢 **{e['time']}**　📍 {e['venue']}\n"
        message += f"📣 {e['artist']}\n"
        message += LINE + "\n\n"

try:
    response = requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)

    if response.status_code == 204:
        print("✅ Discord投稿完了！")
    else:
        print(f"⚠️ 投稿失敗: {response.status_code}")
        print(response.text)

except Exception as e:
    print(f"❌ エラー: {e}")

print("終了しました。")
