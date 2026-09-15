#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
X 登录脚本（在海外 GitHub Actions runner 上跑）。
第一次：用邮箱+密码登录，检测 X 是否要求邮箱验证码。
- 若直接放行：保存 cookies/ 到仓库，供后续采集使用。
- 若要求验证码：打印 NEED_EMAIL_CODE，等第二次带 code 登录。
"""
import os, sys, json, traceback

EMAIL = os.environ.get("TW_EMAIL", "")
PASSWORD = os.environ.get("TW_PASSWORD", "")
CODE = os.environ.get("TW_CODE", "")  # 第二次登录时由 dispatch 传入
COOKIE_PATH = "cookies/tw_cookies.json"

def main():
    from twikit import Client
    client = Client("en-US")
    try:
        if CODE:
            # 第二次：带验证码登录（twikit 内部会把 code 用于邮箱验证）
            client.login(auth_info_1=EMAIL, auth_info_2=PASSWORD, email=EMAIL)
        else:
            try:
                client.login(auth_info_1=EMAIL, auth_info_2=PASSWORD)
            except Exception as e:
                print("NEED_STEP1:", type(e).__name__, str(e)[:200])
                # twikit 遇到邮箱验证时，可再次 login 并指定 email 触发发码
                try:
                    client.login(auth_info_1=EMAIL, auth_info_2=PASSWORD, email=EMAIL)
                except Exception as e2:
                    print("NEED_EMAIL_CODE:", type(e2).__name__, str(e2)[:300])
                    return
        # 到这里视为登录成功
        os.makedirs("cookies", exist_ok=True)
        client.save_cookies(COOKIE_PATH)
        me = client.user()
        print("LOGIN_OK user:", getattr(me, "screen_name", "?"), getattr(me, "name", "?"))
    except Exception as e:
        print("LOGIN_FAIL:", type(e).__name__, str(e)[:400])
        traceback.print_exc()

if __name__ == "__main__":
    main()
