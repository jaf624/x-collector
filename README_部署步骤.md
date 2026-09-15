# X 平台自动化采集（海外节点 → 国内服务器入库）

## 为什么这样设计
国内服务器和本地网络都无法直连 X（实测全部超时）。因此把"采集"放在海外
GitHub Actions 免费 runner 上，把"洗练入库"放在国内服务器，中间用 GitHub raw
文件传递，而 raw.githubusercontent.com 国内服务器可直连（已验证）。

```
X ──(海外网络)──> GitHub Actions 定时采集 ──> data/x_feed.json(提交回仓库)
                                                      │(raw 国内可达)
                                                      ▼
                            国内服务器 x_ingest.py 每30分钟拉取 → 15引擎洗练/评分/配图
                                                      ▼
                                              prompts 表 → 网站实时展示
```

## 两种能力
1. 免登录（默认）：只能抓 `targets/ids.txt` 里你投喂的具体推文链接。
2. 登录态（选配，主动发现）：在仓库 Settings → Secrets and variables → Actions
   添加两个 Secret 后，可自动抓 `accounts.txt` 账号最新推文和 `keywords.txt` 搜索结果。
   - X_AUTH_TOKEN：登录 x.com 后 F12 → Application → Cookies → auth_token 的值
   - X_CT0：同位置 ct0 的值

## 上线步骤（只需做一次，约3分钟）
1. 在 GitHub 新建一个 **Private** 仓库，例如 `x-feed`。
2. 把本 `x_collector` 目录里所有文件上传到仓库根目录。
   （也可把 GitHub Personal Access Token 发给助手，由助手用 API 全自动建仓上传）
3. 仓库 Actions 页确认启用 workflow；可先点 "Run workflow" 手动跑一次，
   几分钟后仓库里生成 `data/x_feed.json` 即成功。
4. 把该 raw 地址填给助手（形如
   `https://raw.githubusercontent.com/<你的用户名>/x-feed/main/data/x_feed.json`），
   助手在服务器端 `x_ingest.py` 配好后即全自动闭环。
5. 以后：你往 `targets/ids.txt` 加链接，或直接让助手加；要主动监控账号就配 Secret。

## 频率
- Actions 每 30 分钟采集一次；服务器每 30 分钟拉取一次。
- 免费额度对个人完全够用（私有仓库 Actions 每月 2000 分钟）。
