# 从别的设备访问（可选，进阶）

telegram-mcp 默认只监听 `127.0.0.1`，只有本机的 AI 客户端能用。它的 HTTP 接口**没有任何密码**，
所以想让别的电脑、手机或 claude.ai 这类云端客户端使用时，必须在前面加一层鉴权。下面是用
Cloudflare Tunnel + Cloudflare Access 的思路（本程序 v0.2 计划做成向导，目前需要手动操作）。

1. 在本机安装 `cloudflared`，在 Cloudflare Zero Trust 里新建一条**专用**隧道（不要复用其他机器上的隧道，
   同一隧道多个连接器会被分流）。
2. 给隧道加一个公共主机名，服务填 `http://127.0.0.1:<本程序里显示的端口>`。
3. 在 Zero Trust → Access 里为这个主机名建一个自托管应用，策略只允许你的 Service Token
   （或你的邮箱登录）。**没有 Access 保护之前不要让这个地址生效。**
4. 在 telegram-mcp 的 `.env` 里加上 `MCP_ALLOWED_HOSTS=<你的主机名>`（否则会因为 Host 不是本机被拒绝），
   在本程序里点「重启」。
5. 客户端用 `https://<你的主机名>/mcp`，并带上 Service Token 的两个请求头
   （`CF-Access-Client-Id`、`CF-Access-Client-Secret`）。

注意：

- 电脑关机或本程序退出时，远程访问也会失效。
- 建议只开只读工具，并保持聊天白名单尽量小。
- 撤销访问：删除 Access 里的 Service Token，或在手机 Telegram「设置 → 设备」里移除这台设备。
