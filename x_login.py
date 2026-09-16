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
        time.sleep(1)

        # ---- 状态机：自适应推进 邮箱→(Use password)→密码→登录，最多 80 秒 ----
        CLICK_CENTERED = """(label) => {
            const btns = Array.from(document.querySelectorAll('div[role="button"],button,a,span'));
            for (const b of btns) {
                const t=(b.innerText||b.textContent||'').trim();
                if (t===label) {
                    const r=b.getBoundingClientRect();
                    if (r.width>0 && r.height>0 && r.x>300 && r.x<1000 && r.y>50 && r.y<800) { b.click(); return true; }
                }
            }
            return false;
        }"""
        FIND_PWD = """() => {
            const ps = Array.from(document.querySelectorAll('input[name="password"]'));
            return ps.find(e => {
                const r=e.getBoundingClientRect();
                return r.width>0 && r.height>0 && !e.hasAttribute('inert') && !e.closest('[inert]') && r.x>300;
            }) || null;
        }"""
        password_filled = False
        login_clicked = False
        deadline = time.time() + 80
        last = ""
        while time.time() < deadline:
            cookies = ctx.cookies("https://x.com")
            if any(c["name"] == "auth_token" for c in cookies):
                print("auth_token appeared in loop")
                break
            try:
                body = page.inner_text("body", timeout=2000).lower()
            except Exception:
                body = ""
            if any(k in body for k in ["verification code", "enter the code", "check your email",
                                       "confirmation code", "we sent you a code"]):
                print("NEED_CODE detected in loop")
                page.screenshot(path="/tmp/05_need_code.png", full_page=True)
                if not CODE:
                    ctx.storage_state(path=STATE_FILE)
                    print("NEED_CODE: X 要求邮箱验证码，未提供 TW_CODE")
                    browser.close(); sys.exit(3)
            tag = f"{page.url.split('#')[-1]}|pwd={password_filled}|login={login_clicked}"
            if tag != last:
                print("STATE:", tag[:150]); last = tag
            # a) Confirm account 页：点 Use password
            if not password_filled:
                try:
                    if page.evaluate(CLICK_CENTERED, "Use password"):
                        print("clicked Use password"); time.sleep(2)
                except Exception:
                    pass
            # b) 密码框就绪：JS 设值
            if not password_filled:
                try:
                    if page.evaluate(FIND_PWD):
                        r = page.evaluate(
                            """(pw) => {
                                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                                setter.call(pw, %s);
                                pw.dispatchEvent(new Event('input',{bubbles:true}));
                                pw.dispatchEvent(new Event('change',{bubbles:true}));
                                return 'set';
                            }""" % json.dumps(PASSWORD),
                            page.evaluate_handle(FIND_PWD)
                        )
                        if r == "set":
                            password_filled = True
                            print("step2 password typed via JS"); time.sleep(1)
                except Exception as ex:
                    print("pwd loop err:", repr(ex)[:100])
            # c) 还在邮箱步：点 Continue
            if not password_filled:
                try:
                    page.evaluate(CLICK_CENTERED, "Continue")
                except Exception:
                    pass
            # d) 密码已填：点 Log in
            if password_filled and not login_clicked:
                try:
                    if page.evaluate(CLICK_CENTERED, "Log in"):
                        login_clicked = True
                        print("clicked Log in"); time.sleep(4)
                except Exception:
                    pass
            time.sleep(2)
        dump("after_loop")
        page.screenshot(path="/tmp/04_after_login.png", full_page=True)

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
