#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录 + 诊断：登录后立即 dump session cookies，确认真实登录态。"""
import os
from twikit import Client

EMAIL = os.environ.get("TW_EMAIL", "")
PASSWORD = os.environ.get("TW_PASSWORD", "")

def main():
    client = Client("en-US")
    client.login(auth_info_1=EMAIL, password=PASSWORD)
    # 关键：dump session cookies
    try:
        ck = client.session.cookies
        print("SESSION_COOKIE_COUNT:", len(ck))
        for c in ck.jar:
            print("  CK:", c.name)
    except Exception as e:
        print("dump cookies fail:", e)
    # 试一个需要登录的请求
    try:
        tweets = client.get_latest_tweets(count=1)
        print("TIMELINE_OK got", len(tweets), "tweet(s)")
    except Exception as e:
        print("TIMELINE_FAIL:", type(e).__name__, str(e)[:200])
    os.makedirs("cookies", exist_ok=True)
    client.save_cookies("cookies/tw_cookies.json")
    import json
    print("SAVED_BYTES:", os.path.getsize("cookies/tw_cookies.json"))

if __name__ == "__main__":
    main()
