from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import requests
import os
from datetime import datetime

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

if not WEBHOOK_URL:
    print("❌ DISCORD_WEBHOOK_URL が設定されていません")
    exit(1)

print("=== 今日の名古屋エリアイベント（サンデーフォーク + バンテリンドーム） ===\n")

today = datetime.now()
TARGET_DATE = today.strftime("%Y%m%d")
weekday = ["月", "火", "水", "木", "金", "土", "日"][today.weekday()]

events = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # サンデーフォーク
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
                
                events.append({"time": time_text, "venue": venue, "artist": artist})

    # バンテリンドーム
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
            time_match = re.search(r"開始\s*(\d{1,2}:\d{2})", day_text)
            if not time_match:
                time_match = re.search(r"(\d{1,2}:\d{2})", day_text)
            time_text = time_match.group(1) if time_match else "時間情報なし"
            
            events.append({
                "time": time_text,
                "venue": "バンテリンドームナゴヤ",
                "artist": event_text
            })

# ================== 投稿 ==================
if len(events) == 0:
    print("ℹ️ 今日はイベント0件でした。投稿をスキップします。")
else:
    events.sort(key=lambda x: x["time"] if ":" in x["time"] else "99:99")
    
    message = f"**名古屋ライブ情報**（サンデーフォーク＋ドーム対応ベータ版）\n"
    message += f"対象日: {today.strftime('%m月%d日')}（{weekday}）\n"
    message += f"合計 **{len(events)}件**\n\n"
    
    for e in events:
        message += f"⏰ **{e['time']}**　📍 {e['venue']}\n"
        message += f"🎤 {e['artist']}\n\n"

    try:
        response = requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
        if response.status_code == 204:
            print("✅ Discord投稿完了！")
        else:
            print(f"⚠️ 投稿失敗: {response.status_code}")
    except Exception as e:
        print(f"❌ エラー: {e}")

print("終了しました。")
