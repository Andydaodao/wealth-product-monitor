# 中银理财雷达（第一版）

本地整理中国银行和中银理财公开产品信息，展示产品观察池、即将开放、基础偏好标签、来源状态和发现历史。工具不登录银行账户，不查询个人信息，也不执行交易。

## 安装与启动（Windows PowerShell）

```powershell
cd C:\work\平台化\tmp\boc_monitor\wealth-product-monitor
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item config.example.json config.json
.\scripts\run.ps1
```

浏览器打开 <http://127.0.0.1:8765>。按 `Ctrl+C` 停止服务。

程序首次启动会载入 2026-09-14 从中银理财公开首页与公告页读取的 8 条记录，让当前代理限制环境也能查看界面；页面明确标注为“公开快照”。首次发现时间指本地入库时间，不表示产品刚发行。点击“立即检查公开信息”可联网刷新。数据库位于 `data/wealth_monitor.db`。

## 配置和测试

编辑 `config.json` 可修改监听地址、端口、监控间隔和偏好。第一版默认偏好为 R1/R2、最短持有期不超过 90 天。筛选标签只用于缩小信息范围，不代表收益预测或投资建议。

程序启动后立即检查一次，此后每 12 小时扫描一次，并随机延后 0～60 秒，避免固定时刻重复请求。首次打开时如果同步尚未结束，页面会显示“正在同步”并自动刷新。电脑关机、休眠或程序停止时不会扫描。可以在 `config.json` 中修改 `scan_interval_minutes`，12 小时对应 `720`。

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 当前数据边界

- 中银理财产品首页：解析产品名称、产品代码和名称中明确出现的最短持有期。
- 中银理财公告：解析公开公告列表的开放预告与发行公告；具体时刻未披露时保持为空。
- 募集规模上限与风险等级只有在公开页面明确提供时才保存。
- 实时剩余额度在公开页面不可得，页面始终如实标记。
- 企业代理拦截银行站点时，监控状态显示“异常”，本地服务和历史数据仍可使用。

## 版本范围

这是可交互的首版预览，尚未达到规格中的完整 V1 验收。已完成本地服务、SQLite、公开快照、产品与公告列表解析、首次发现去重、搜索、风险/持有期筛选、产品详情、来源状态和定时检查。产品生命周期使用 `UPCOMING / ACTIVE / HISTORICAL`，用户关注单独保存在 `watchlist` 表中，因此在售产品也能同时加入“我的关注”。

Windows 通知、ntfy、PDF 附件解析、中国银行动态查询平台、完整变更事件与产品合并、同系列历史对比、24 小时稳定性验证尚未完成。当前电脑的企业代理要求认证，银行实时抓取尚未验证成功；不会绕过代理或银行安全控制。

公开来源：[中银理财产品首页](https://www.bocwm.cn/)、[产品公告](https://www.bocwm.cn/html/1/198/197/index.html)、[纯债7天持有期2号详情](https://www.bocwm.cn/html/1/4/9494.html)。

## 发布到 GitHub Pages

项目保留本地 FastAPI 版本，同时支持生成 GitHub Pages 静态网站。静态版在浏览器中完成搜索和筛选，不能直接修改本地关注列表。GitHub Actions 在北京时间约 09:17 和 21:17 自动扫描；GitHub 调度繁忙时可能稍有延迟。

本地预览静态网站：

```powershell
.\.venv\Scripts\python.exe .\scripts\build_site.py
.\.venv\Scripts\python.exe -m http.server 8000 --directory public
```

浏览器打开 <http://127.0.0.1:8000>。生成目录 `public/` 不提交，Actions 会在云端重新生成。`data/cloud_state.json` 保存公开产品、发现事件和最近的来源状态，供下一次定时扫描比较；本地数据库和关注列表不会上传。

首次部署：

1. 在 GitHub 创建一个公开的空仓库。
2. 将本项目提交并推送到仓库默认分支。
3. 打开仓库 `Settings → Pages`，将 `Source` 设为 `GitHub Actions`。
4. 打开 `Actions → 扫描并发布理财雷达 → Run workflow`，手动执行第一次扫描。
5. 工作流完成后，在 `Settings → Pages` 查看公开网址。
