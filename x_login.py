#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第一步：诊断当前 twikit 版本的真实登录接口。"""
import os, inspect
import twikit
print("twikit version:", getattr(twikit, "__version__", "?"))
from twikit import Client
print("login signature:", inspect.signature(Client.login))
meths = [m for m in dir(Client) if not m.startswith('_') and any(k in m.lower() for k in ['login','mail','verif','activ','auth','code'])]
print("relevant methods:", meths)
try:
    from twikit.errors import *
    import twikit.errors as E
    print("errors:", [x for x in dir(E) if not x.startswith('_')])
except Exception as e:
    print("errors import:", e)
