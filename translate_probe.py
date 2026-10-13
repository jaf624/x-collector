# -*- coding: utf-8 -*-
"""端到端验证 intel_collect.gtx_translate（真实函数）翻译资源/能源/军事英文硬新闻。"""
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
    print("=" * 16, tag, "=" * 16)
    print("ZH:", zh)
    assert zh and len(zh) >= 10, "翻译为空: " + tag
print("GTX_PROBE_DONE")
