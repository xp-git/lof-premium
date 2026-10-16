# LOF 基金溢价监控（全部 A 股 LOF）

覆盖沪深全部约 390 只 LOF 基金的实时溢价监控工具，支持两种使用方式：

| 文件 | 说明 |
|------|------|
| `index.html` | **网页版**（零依赖、零构建），部署到 GitHub Pages 后浏览器直接访问 |
| `lof_premium_gui.py` | **桌面版**（tkinter 图形界面），本地运行 |
| `fetch_data.py` | GitHub Action 定时任务脚本：抓取全部 LOF 净值生成 `data.json` |
| `.github/workflows/update-data.yml` | 定时任务定义（交易日 09:30 / 16:00 / 22:00 北京时间自动运行） |

## 功能

- 实时现价、最新单位净值
- 净值溢价率（红=溢价、绿=折价）
- 三日均溢价、成交额（取整）、预计收益率 / 收益额（按 1 万元本金）
- 点击表头排序、关键字搜索、自动刷新、点击行查看详情（含申购/赎回状态）

> 注：天天基金已于 2024 年下线基金盘中实时估值功能，「估算净值」列暂不可用；
> 页面会自动探测，若接口恢复将自动显示。溢价率以最新净值为准。

## 网页版部署到 GitHub Pages

```bash
git init
git add .
git commit -m "LOF基金溢价监控"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

然后在 GitHub 仓库页面：**Settings → Pages → Source 选 `main` 分支 / `/ (root)` → Save**，
约 1 分钟后即可访问：`https://<你的用户名>.github.io/<仓库名>/`

**重要**：推送后到仓库的 **Actions** 页面，选择 "Update LOF data" 工作流，
点 **Run workflow** 手动运行一次，生成 `data.json`（净值快照数据）。
之后每个交易日 09:30 / 16:00 / 22:00（北京时间）会自动运行。

## 净值数据机制（v2）

- 页面优先用浏览器实时接口获取净值；若访客网络访问不了（部分网络环境会发生），
  自动回退到仓库内的 `data.json` 快照（同源加载，不受访客网络限制）
- `data.json` 由 GitHub Action 在 GitHub 服务器上定时抓取并提交，包含：
  最新净值、净值日期、三日均溢价、申购/赎回状态
- 现价 / 成交额始终为浏览器实时拉取（东方财富行情接口）

## 桌面版运行

```bash
pip install requests
python lof_premium_gui.py          # 图形界面
python lof_premium_gui.py --cli    # 命令行模式
```

## 数据说明

数据来自东方财富 / 天天基金公开接口（行情、净值、日K）。数据可能有延迟或误差，
仅供研究参考，不构成投资建议。
