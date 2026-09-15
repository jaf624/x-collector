#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真登录：用 twikit 2.3.3 接口。先裸登录看 X 反应。"""
import os, traceback
from twikit import Client

EMAIL = os.environ.get("TW_EMAIL", "")
PASSWORD = os.environ.get("TW_PASSWORD", "")
CODE = os.environ.get("TW_CODE", "")

def main():
    client = Client("en-US")
    try:
        if CODE:
            # 新版把验证码走 totp_secret/或在 login 内 input；这里直接再试一次
            client.login(auth_info_1=EMAIL, password=PASSWORD)
        else:
            client.login(auth_info_1=EMAIL, password=PASSWORD)
        os.makedirs("cookies", exist_ok=True)
        client.save_cookies("cookies/tw_cookies.json")
        me = client.user()
        print("LOGIN_OK user:", getattr(me, "screen_name", "?"), getattr(me, "name", "?"))
    except Exception as e:
        print("LOGIN_FAIL:", type(e).__name__, str(e)[:400])
        traceback.print_exc()

if __name__ == "__main__":
    main()
