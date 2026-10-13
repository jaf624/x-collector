# -*- coding: utf-8 -*-
"""海外节点验证 Google gtx 翻译：对几段真实英文硬新闻（资源/能源/军事）翻译，打印中文。"""
import intel_collect as ic

cases = [
    ("Lynas稀土标题", "Lynas plans Brazil rare earths plant with state support"),
    ("Lynas摘要", "Lynas Rare Earths has presented plans to build a rare earth oxide separation plant "
     "in Brazil's Minas Gerais state, as the government considers backing a project that could become "
     "one of the largest such facilities outside China. The proposal forms part of Lynas' expansion "
     "into Brazil through its $672 million acquisition of Meteoric Resources. State development bank "
     "BNDES is evaluating potential financing."),
    ("能源通道", "The United States is pressuring Venezuela to expel Chinese oil workers and cut "
     "Chinese energy projects, threatening Beijing's overseas energy supply corridor."),
    ("军事", "The U.S. military is deploying a new missile system in the first island chain, "
     "a move targeting China's naval expansion."),
]
for tag, en in cases:
    zh = ic.gtx_translate(en)
    print("=" * 20, tag, "=" * 20)
    print("EN:", en[:120])
    print("ZH:", zh)
    print()
print("GTX_PROBE_DONE")
