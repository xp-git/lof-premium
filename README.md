# LOF 基金溢价监控（全部 A 股 LOF）

覆盖沪深全部约 390 只 LOF 基金的实时溢价监控工具，支持两种使用方式：

| 文件 | 说明 |
|------|------|
| `index.html` | **网页版**（单文件、零依赖、零构建），部署到 GitHub Pages 后浏览器直接访问 |
| `lof_premium_gui.py` | **桌面版**（tkinter 图形界面），本地运行 |

## 功能

- 实时现价、最新单位净值、盘中估算净值
- 溢价率 / 估算溢价率（红=溢价、绿=折价）
- 三日均溢价、成交额（取整）、预计收益率 / 收益额（按 1 万元本金）
- 点击表头排序、关键字搜索、自动刷新、点击行查看详情（含申购/赎回状态）

## 网页版部署到 GitHub Pages

```bash
git init
git add index.html lof_premium_gui.py README.md
git commit -m "LOF基金溢价监控"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

然后在 GitHub 仓库页面：**Settings → Pages → Source 选 `main` 分支 / `/ (root)` → Save**，
约 1 分钟后即可访问：`https://<你的用户名>.github.io/<仓库名>/`

## 桌面版运行

```bash
pip install requests
python lof_premium_gui.py          # 图形界面
python lof_premium_gui.py --cli    # 命令行模式
```

## 数据说明

数据来自东方财富 / 天天基金公开接口（行情、净值、估值、日K），全部在浏览器本地实时计算，
无后端、无数据存储。数据可能延迟或有误差，仅供研究参考，不构成投资建议。
