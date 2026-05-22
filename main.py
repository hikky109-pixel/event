from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import requests
import os
from datetime import datetime, timedelta, timezone

# 日本時間
JST = timezone(timedelta(hours=9))
today = datetime.now(JST)
TARGET_DATE = today.strftime("%Y%m%d")
weekday = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not WEBHOOK_URL:
    print("❌ DISCORD_WEBHOOK_URL が設定されていません")
    exit(1)

print(f"=== 名古屋エリアイベント（イベント＋ドームベータ版） ===\n")
print(f"対象日: {today.strftime('%m月%d日')}（{weekday}）\n")

events = []
seen = set()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ==================== サンデーフォーク ====================
    print("🔍 サンデーフォークを検索中...")
    page.goto("https://www.sundayfolk.com/calendar/2026/05/", timeout=60000)
    page.wait_for_timeout(10000)
    soup = BeautifulSoup(page.content(), "html.parser")
    
    block = soup.find("div", id=f"d{TARGET_DATE}")
    if block:
        table = block.find("table", class_="tableList")
        if table:
            for row in table.find_all("tr")[1:]:
                cols = row.find_all("td")
                if len(cols) < 5: continue
                
                artist = cols[0].get_text(strip=True)
                venue = cols[3].get_text(strip=True)
                time_text = cols[2].get_text(strip=True)
                
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
                        detail_text = BeautifulSoup(page.content(), "html.parser").get_text()
                        m = re.search(r"(\d{1,2}:\d{2})", detail_text)
                        time_text = m.group(0) if m else "時間情報なし"
                
                key = f"{time_text}|{artist}"
                if key not in seen:
                    seen.add(key)
                    events.append({"time": time_text, "venue": venue, "artist": artist})

    # ==================== バンテリンドーム ====================
    print("🔍 バンテリンドームを検索中...")
    page.goto("https://www.nagoya-dome.co.jp/sp/eventcalen.php", timeout=60000)
    page.wait_for_timeout(12000)
    soup = BeautifulSoup(page.content(), "html.parser")
    
    m = today.month
    d = today.day
    patterns = [f"{m}/{d}", f"0{m}/{d}", f"{m}/{d:02d}", f"0{m}/{d:02d}"]
    
    for day_td in soup.find_all("td", class_="eventDay"):
        day_text = day_td.get_text(strip=True)
        if not any(p in day_text for p in patterns):
            continue
            
        row = day_td.find_parent("tr")
        if not row: continue
        title_row = row.find_next_sibling("tr")
        if not title_row: continue
        title_td = title_row.find("td", class_="eventTitle")
        if title_td:
            event_text = " ".join(title_td.get_text(strip=True).split())
            time_match = re.search(r"(\d{1,2}:\d{2})", day_text)
            time_text = time_match.group(1) if time_match else "時間情報なし"
            
            key = f"{time_text}|{event_text}"
            if key not in seen:
                seen.add(key)
                events.append({"time": time_text, "venue": "バンテリンドームナゴヤ", "artist": event_text})

    # ==================== キョードー東海 ====================
    print("🔍 キョードー東海を検索中...")
    page.goto("https://kyodotokai.co.jp/events/calendor", timeout=60000)
    page.wait_for_timeout(12000)
    
    soup = BeautifulSoup(page.content(), "html.parser")
    
    for strong in soup.find_all("strong"):
        if strong.get_text(strip=True) == str(today.day):
            tr = strong.find_parent("tr")
            if tr:
                for link in tr.find_all("a", href=re.compile(r'/events/detail/')):
                    artist = link.get("title") or link.get_text(strip=True)
                    detail_url = "https://kyodotokai.co.jp" + link.get("href")
                    
                    page.goto(detail_url, timeout=30000)
                    page.wait_for_timeout(8000)
                    
                    full_text = BeautifulSoup(page.content(), "html.parser").get_text()
                    
                    # 時間
                    day_block = re.search(r'2026年05月0?' + str(today.day) + r'日.*?開　演\s*(\d{1,2}[:：]\d{2})', full_text, re.DOTALL)
                    time_text = day_block.group(1).replace('：', ':') if day_block else "時間情報なし"
                    
                    # 会場
                    venue_match = re.search(r'会[　\s]*場[　\s\n]*([^\n\r]{5,120})', full_text)
                    venue = venue_match.group(1).strip() if venue_match else "キョードー東海"
                    venue = re.sub(r'\s+', ' ', venue).strip()
                    
                    # 名古屋フィルター
                    nagoya_keywords = ["名古屋", "Zepp", "ポートベース", "IGアリーナ", "ガイシホール", "Niterra", "日本特殊陶業", "中電", "御園座", "クワトロ", "瑞穂", "栄", "NAGOYA JAMMIN", "愛知県芸術劇場"]
                    if any(k in venue for k in nagoya_keywords):
                        key = f"{time_text}|{artist}|{venue}"
                        if key not in seen:
                            seen.add(key)
                            events.append({"time": time_text, "venue": venue, "artist": artist})

# ================== Discord投稿 ==================
if len(events) == 0:
    print("ℹ️ 今日はイベント0件でした。投稿をスキップします。")
else:
    events.sort(key=lambda x: x["time"] if ":" in str(x["time"]) else "99:99")
    
    LINE = "─" * 28
    
    message = f"**名古屋イベント情報**\n"
    message += f"{today.strftime('%m月%d日')}（{weekday}）\n"
    message += "（イベント＋ドームベータ版）\n"
    message += LINE + "\n"
    message += f"合計 **{len(events)}件**\n"
    message += LINE + "\n\n"
    
    for e in events:
        message += f"⏰ **{e['time']}**　📍 {e['venue']}\n"
        message += f"🎤 {e['artist']}\n"
        message += LINE + "\n\n"

    try:
        response = requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
        if response.status_code == 204:
            print("✅ Discord投稿完了！")
        else:
            print(f"⚠️ 投稿失敗: {response.status_code}")
    except Exception as e:
        print(f"❌ エラー: {e}")

print("終了しました。")
