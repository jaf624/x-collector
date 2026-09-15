#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""twikit 2.3.3 是异步库，必须 asyncio 调用。"""
import os, asyncio
from twikit import Client

async def main():
    client = Client("en-US")
    await client.login(auth_info_1=os.environ["TW_EMAIL"], password=os.environ["TW_PASSWORD"])
    me = await client.user()
    print("LOGIN_OK screen_name:", getattr(me, "screen_name", "?"), "name:", getattr(me, "name", "?"))
    os.makedirs("cookies", exist_ok=True)
    client.save_cookies("cookies/tw_cookies.json")
    print("SAVED_BYTES:", os.path.getsize("cookies/tw_cookies.json"))

asyncio.run(main())
