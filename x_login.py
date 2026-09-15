#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用真浏览器(Playwright Chromium)登录 X，绕过纯 HTTP 登录的 Castle 反爬。
流程：email -> (可能的额外验证) -> password -> (可能的邮箱验证码) -> 成功。
第一次跑不传 code；若 X 要求邮箱验证码，打印 NEED_CODE 并退出；
拿到验证码后，把 code 作为输入再跑一次即可。"""
import os, time, json, sys
from playwright.sync_api import sync_playwright

EMAIL = os.environ["TW_EMAIL"]
PASSWORD = os.environ["TW_PASSWORD"]
CODE = os.environ.get("TW_CODE", "").strip()

STATE_FILE = "cookies/storage_state.json"
COOKIE_FILE = "cookies/tw_cookies.json"
os.makedirs("cookies", exist_ok=True)
page = None


def dump(tag):
    try:
        print(f"[STATE] {tag} url={page.url}")
    except Exception:
        pass


def type_first(page, selectors, text, timeout=8000):
    for sel in selectors:
        try:
            el = page.wait_for_selector(sel, timeout=timeout, state="visible")
            el.click()
            el.fill(text)
            return True
        except Exception:
            continue
    return False


def click_text(page, texts, timeout=8000):
    for t in texts:
        for sel in [f'div[role="button"]:has-text("{t}")', f'span:has-text("{t}")', f'button:has-text("{t}")']:
            try:
                page.click(sel, timeout=timeout)
                return True
            except Exception:
                continue
    return False


def main():
    global page
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 850},
            locale="en-US",
        )
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = ctx.new_page()
        page.goto("https://x.com/i/flow/login", timeout=60000, wait_until="domcontentloaded")
        time.sleep(10)
        page.screenshot(path="/tmp/01_open.png", full_page=True)
        dump("open_login")

        # 调试：打印页面上所有 input 的真实属性
        try:
            inputs = page.evaluate(
                """() => Array.from(document.querySelectorAll('input')).map(e => ({
                    type: e.type, name: e.name, placeholder: e.placeholder,
                    autocomplete: e.autocomplete, testid: e.getAttribute('data-testid'),
                    visible: !!(e.offsetWidth||e.offsetHeight||e.getClientRects().length)
                }))"""
            )
            print("ALL_INPUTS:", json.dumps(inputs, ensure_ascii=False))
        except Exception as ex:
            print("dump inputs failed:", repr(ex))

        # 1) 填邮箱（用真实 name，只取可见的 modal 里那个）
        ok = False
        try:
            el = page.locator('input[name="username_or_email"]:visible').first
            el.wait_for(state="visible", timeout=25000)
            el.click()
            el.fill(EMAIL)
            ok = True
        except Exception as ex:
            print("fill email failed:", repr(ex))
        print("step1 email typed:", ok)
        # 提交：优先回车，其次点黑色 Continue（取最后一个，避免误点背景）
        try:
            el.press("Enter")
        except Exception as ex:
            print("press enter failed:", repr(ex))
        time.sleep(3)
        if "password" not in (page.locator('input[name="password"]').get_attribute("inert") or ""):
            pass
        try:
            page.locator('div[role="button"]:visible:has-text("Continue")').last.click(timeout=6000)
        except Exception as ex:
            print("click continue(last) failed:", repr(ex))
        time.sleep(6)
        dump("after_email")
        page.screenshot(path="/tmp/03_after_email.png", full_page=True)

        # 2) 填密码
        pwd_ok = False
        try:
            pwd = page.locator('input[name="password"]:visible').first
            pwd.wait_for(state="visible", timeout=15000)
            pwd.click()
            pwd.fill(PASSWORD)
            pwd_ok = True
        except Exception as ex:
            print("fill password failed:", repr(ex))
        print("step2 password typed:", pwd_ok)

        # 点 Log in
        try:
            page.locator('div[role="button"]:visible:has-text("Log in")').first.click(timeout=8000)
        except Exception as ex:
            print("click login failed:", repr(ex))
        time.sleep(8)
        dump("after_login_click")
        page.screenshot(path="/tmp/04_after_login.png", full_page=True)

        needs_code = False
        try:
            body = page.inner_text("body", timeout=5000).lower()
            if "verification code" in body or "enter the code" in body or "check your email" in body or "confirmation code" in body:
                needs_code = True
        except Exception:
            pass

        if needs_code and not CODE:
            print("NEED_CODE: X 要求邮箱验证码，但本次未提供 TW_CODE")
            ctx.storage_state(path=STATE_FILE)
            browser.close()
            sys.exit(3)

        if needs_code and CODE:
            type_first(page, ['input[name="text"]', 'input[inputmode="numeric"]', 'input[maxlength="6"]'], CODE, timeout=6000)
            click_text(page, ["Next", "Submit", "Verify", "下一步"])
            time.sleep(6)
            dump("after_code")

        cookies = ctx.cookies("https://x.com")
        auth_token = next((c["value"] for c in cookies if c["name"] == "auth_token"), None)
        ct0 = next((c["value"] for c in cookies if c["name"] == "ct0"), None)
        print("auth_token found:", bool(auth_token))
        print("ct0 found:", bool(ct0))

        if auth_token and ct0:
            with open(COOKIE_FILE, "w") as f:
                json.dump({"auth_token": auth_token, "ct0": ct0}, f)
            print("SAVED:", COOKIE_FILE)
            print("LOGIN_OK")
            browser.close()
            return

        print("cookie names:", [c["name"] for c in cookies])
        print("LOGIN_FAIL: 未拿到 auth_token")
        browser.close()
        sys.exit(1)


try:
    main()
except SystemExit:
    raise
except Exception as e:
    print("ERROR:", repr(e))
    sys.exit(2)
