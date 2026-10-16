#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LOF 基金溢价监控（全部 A 股 LOF）
================================
功能：
  - 拉取全部沪深 LOF 基金（东财行情中心 b:MK0404~MK0407，共约 390 只）
  - 实时现价、最新单位净值、盘中估算净值（fundgz，失败自动留空）
  - 溢价/估算溢价、三日均溢价、成交额、预计收益率/收益额
  - 点击表头排序、关键字搜索、自动刷新、双击查看详情

列说明：
  溢价/估算      净值溢价率 / 估算溢价率（%），溢价为正=现价高于净值（红）
  三日均溢       最近 3 个交易日溢价率均值（%）
  预计收益率     (估算净值或净值 - 现价) / 现价，即场内买入后价格向净值收敛的收益
  预计收益额     按 1 万元本金计算的预计收益金额

用法：
  python lof_premium_gui.py          # 启动图形界面
  python lof_premium_gui.py --cli    # 命令行模式，按估算溢价排序打印

依赖：requests（pip install requests）；界面用标准库 tkinter。
免责声明：数据来自公开网络接口，可能延迟或有误，仅供研究参考，不构成投资建议。
"""

import json
import queue
import re
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests

# ----------------------------------------------------------------------
# 数据层
# ----------------------------------------------------------------------

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
SPOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"
GZ_URL = "https://fundgz.1234567.com.cn/js/{code}.js"

_session = requests.Session()
_session.headers.update(HEADERS)


def _f(v):
    """安全转 float，失败返回 None（东财停牌时返回 '-'）"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_lof_spot():
    """全部沪深 LOF 实时行情：代码/名称/市场/现价/涨跌幅/成交额/昨收"""
    rows = []
    pn = 1
    while True:
        params = {
            "pn": pn, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "fid": "f6", "fs": "b:MK0404,b:MK0405,b:MK0406,b:MK0407",
            "fields": "f12,f13,f14,f2,f3,f6,f18",
        }
        r = _session.get(SPOT_URL, params=params, timeout=15)
        data = r.json().get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        for d in diff:
            rows.append({
                "code": d["f12"],
                "mkt": d["f13"],          # 0=深 1=沪
                "name": d["f14"],
                "price": _f(d.get("f2")),
                "pct_chg": _f(d.get("f3")),
                "amount": _f(d.get("f6")),
                "prev_close": _f(d.get("f18")),
            })
        if len(rows) >= int(data.get("total", 0)) or pn > 10:
            break
        pn += 1
    return rows


def fetch_nav_history(code, size=8):
    """历史单位净值（含最新），返回 [(date, nav), ...] 日期降序；失败返回 []"""
    try:
        r = _session.get(
            LSJZ_URL,
            params={"fundCode": code, "pageIndex": 1, "pageSize": size},
            headers={"Referer": "https://fund.eastmoney.com/"},
            timeout=12,
        )
        lst = (r.json().get("Data") or {}).get("LSJZList") or []
        out = []
        for it in lst:
            nav = _f(it.get("DWJZ"))
            if nav:
                out.append((it["FSRQ"], nav, it.get("SGZT") or "", it.get("SHZT") or ""))
        return out
    except Exception:
        return []


def fetch_estimate(code):
    """盘中估算净值（天天基金 fundgz）。失败/无估值返回 (None, None)"""
    try:
        r = _session.get(GZ_URL.format(code=code), timeout=8)
        m = re.search(r"jsonpgz\((\{.*\})\)", r.text)
        if not m:
            return None, None
        d = json.loads(m.group(1))
        return _f(d.get("gsz")), d.get("gztime")
    except Exception:
        return None, None


def fetch_kline(secid, lmt=8):
    """日 K 收盘价（不含复权），返回 [(date, close), ...] 日期降序"""
    try:
        r = _session.get(
            KLINE_URL,
            params={
                "secid": secid, "klt": 101, "fqt": 0, "lmt": lmt, "end": "20500101",
                "fields1": "f1,f2,f3", "fields2": "f51,f53",
            },
            timeout=12,
        )
        kl = ((r.json().get("data") or {}).get("klines")) or []
        out = []
        for line in reversed(kl):  # 接口正序 → 反转为降序
            p = line.split(",")
            c = _f(p[1])
            if c:
                out.append((p[0], c))
        return out
    except Exception:
        return []


def compute_rows(spot, progress=None):
    """并发抓取每只基金的净值/估值/K线，计算各项指标"""
    results = {}
    done = [0]
    lock = threading.Lock()
    total = len(spot)

    def work(f):
        code = f["code"]
        nav_hist = fetch_nav_history(code)
        gsz, gztime = fetch_estimate(code)
        kline = fetch_kline("{}.{}".format(f["mkt"], code))
        with lock:
            done[0] += 1
            if progress:
                progress(done[0], total)
        return code, (nav_hist, (gsz, gztime), kline)

    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(work, f) for f in spot]
        for fu in as_completed(futs):
            try:
                code, payload = fu.result()
                results[code] = payload
            except Exception:
                pass

    rows = []
    for f in spot:
        code = f["code"]
        nav_hist, (gsz, gztime), kline = results.get(
            code, ([], (None, None), []))
        price = f["price"]

        nav = nav_hist[0][1] if nav_hist else None
        nav_date = nav_hist[0][0] if nav_hist else ""

        prem_nav = price / nav - 1 if (price and nav) else None          # 净值溢价
        prem_est = price / gsz - 1 if (price and gsz) else None          # 估算溢价

        # 三日均溢：最近3个交易日 (收盘价/当日净值 - 1) 的均值
        nav_by_date = {d: n for d, n, _, _ in nav_hist}
        prems3 = []
        for d, close in kline[:3]:
            n = nav_by_date.get(d)
            if n:
                prems3.append(close / n - 1)
        prem3 = sum(prems3) / len(prems3) if prems3 else None

        # 预计收益率：价格向估算净值(无则最新净值)收敛
        base = gsz if gsz else nav
        exp_ret = (base / price - 1) if (price and base) else None
        exp_amt = exp_ret * 10000 if exp_ret is not None else None

        rows.append({
            "code": code,
            "name": f["name"],
            "price": price,
            "nav": nav,
            "nav_date": nav_date,
            "gsz": gsz,
            "gztime": gztime,
            "prem_nav": prem_nav,
            "prem_est": prem_est,
            "prem3": prem3,
            "amount": f["amount"],
            "exp_ret": exp_ret,
            "exp_amt": exp_amt,
            "sgzt": nav_hist[0][2] if nav_hist else "",
            "shzt": nav_hist[0][3] if nav_hist else "",
        })
    return rows


# ----------------------------------------------------------------------
# 格式化
# ----------------------------------------------------------------------

def fmt_pct(v, nd=2):
    return "{:.2f}%".format(v * 100) if v is not None else "--"


def fmt_price(v):
    return "{:.3f}".format(v) if v is not None else "--"


def fmt_amount(v):
    """成交额（取整）：≥1亿显示 x.xx亿，否则取整到万元"""
    if v is None:
        return "--"
    if v >= 1e8:
        return "{:.2f}亿".format(v / 1e8)
    return "{:.0f}万".format(v / 1e4)


def sort_key(row, col):
    """排序用数值键；None 排最后"""
    if col == "prem":
        v = row["prem_est"] if row["prem_est"] is not None else row["prem_nav"]
    elif col == "exp_ret":
        v = row["exp_ret"]
    elif col == "exp_amt":
        v = row["exp_amt"]
    else:
        v = row.get(col)
    return (v is None, v if v is not None else 0)


def sort_rows(rows, col, desc):
    """排序：有数据的行在前（按数值升/降序），无数据的行恒排最后"""
    has = [r for r in rows if not sort_key(r, col)[0]]
    none = [r for r in rows if sort_key(r, col)[0]]
    has.sort(key=lambda r: sort_key(r, col)[1], reverse=desc)
    return has + none


# ----------------------------------------------------------------------
# 图形界面
# ----------------------------------------------------------------------

COLUMNS = [
    ("code",    "代码",        80,  "center"),
    ("name",    "名称",        170, "w"),
    ("price",   "现价",        80,  "e"),
    ("nav",     "净值",        80,  "e"),
    ("gsz",     "估算净值",    90,  "e"),
    ("prem",    "溢价/估算",   120, "e"),
    ("prem3",   "三日均溢",    90,  "e"),
    ("amount",  "成交额(取整)",100, "e"),
    ("exp_ret", "预计收益率",  95,  "e"),
    ("exp_amt", "预计收益额",  95,  "e"),
]


def run_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox

    root = tk.Tk()
    root.title("LOF 基金溢价监控 · 全部A股LOF")
    root.geometry("1180x640")

    q = queue.Queue()
    state = {"rows": [], "refreshing": False, "after_id": None}

    # ---------------- 顶部工具栏 ----------------
    bar = ttk.Frame(root, padding=(8, 6))
    bar.pack(fill="x")

    ttk.Label(bar, text="LOF基金", font=("", 12, "bold")).pack(side="left")

    ttk.Label(bar, text="  搜索:").pack(side="left")
    var_search = tk.StringVar()
    ent = ttk.Entry(bar, textvariable=var_search, width=22)
    ent.pack(side="left", padx=4)

    var_auto = tk.BooleanVar(value=False)
    var_interval = tk.IntVar(value=60)

    btn = ttk.Button(bar, text="刷新数据", command=lambda: refresh())
    btn.pack(side="left", padx=(12, 4))
    ttk.Checkbutton(bar, text="自动刷新", variable=var_auto).pack(side="left", padx=(8, 0))
    ttk.Spinbox(bar, from_=15, to=600, increment=15, width=5,
                textvariable=var_interval).pack(side="left", padx=4)
    ttk.Label(bar, text="秒").pack(side="left")

    ttk.Label(bar, foreground="#888",
              text="红=溢价为正  绿=折价 | 双击行看详情 | 点击表头排序").pack(
        side="right")

    # ---------------- 表格 ----------------
    wrap = ttk.Frame(root)
    wrap.pack(fill="both", expand=True, padx=8, pady=(0, 4))

    tree = ttk.Treeview(wrap, columns=[c[0] for c in COLUMNS],
                        show="headings", selectmode="browse")
    vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    hsb = ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    wrap.rowconfigure(0, weight=1)
    wrap.columnconfigure(0, weight=1)

    for cid, text, width, anchor in COLUMNS:
        tree.heading(cid, text=text,
                     command=lambda c=cid: sort_by(c))
        tree.column(cid, width=width, anchor=anchor)

    tree.tag_configure("pos", foreground="#d32f2f")   # 涨/溢价 红
    tree.tag_configure("neg", foreground="#2e7d32")   # 跌/折价 绿
    tree.tag_configure("zero", foreground="#555555")

    # ---------------- 状态栏 ----------------
    status = ttk.Label(root, anchor="w", padding=(10, 3),
                       text="点击“刷新数据”开始拉取（约 20~60 秒）")
    status.pack(fill="x", side="bottom")
    pb = ttk.Progressbar(root, mode="determinate")
    pb.pack(fill="x", side="bottom")

    sort_state = {"col": "prem", "desc": True}

    # ---------------- 渲染 ----------------
    def render():
        tree.delete(*tree.get_children())
        kw = var_search.get().strip().lower()
        rows = state["rows"]
        if kw:
            rows = [r for r in rows
                    if kw in r["code"] or kw in r["name"].lower()]
        for r in rows:
            prem_txt = "{}/{}".format(fmt_pct(r["prem_nav"]), fmt_pct(r["prem_est"]))
            gsz_txt = fmt_price(r["gsz"]) if r["gsz"] else "--"
            vals = (r["code"], r["name"], fmt_price(r["price"]),
                    fmt_price(r["nav"]), gsz_txt, prem_txt,
                    fmt_pct(r["prem3"]), fmt_amount(r["amount"]),
                    fmt_pct(r["exp_ret"]),
                    "{:,.0f}".format(r["exp_amt"]) if r["exp_amt"] is not None else "--")
            # 颜色依据：估算溢价优先，否则净值溢价
            v = r["prem_est"] if r["prem_est"] is not None else r["prem_nav"]
            tag = ("pos",) if (v is not None and v > 1e-9) else \
                  ("neg",) if (v is not None and v < -1e-9) else ("zero",)
            tree.insert("", "end", values=vals, tags=tag)
        status.config(text="显示 {}/{} 只  ·  更新于 {}  ·  {}".format(
            len(rows), len(state["rows"]),
            datetime.now().strftime("%H:%M:%S"),
            sort_tip()))

    def sort_tip():
        name = dict((c[0], c[1]) for c in COLUMNS).get(sort_state["col"], "")
        return "排序: {} {}".format(name, "↓" if sort_state["desc"] else "↑")

    def sort_by(col):
        if sort_state["col"] == col:
            sort_state["desc"] = not sort_state["desc"]
        else:
            sort_state["col"], sort_state["desc"] = col, True
        state["rows"] = sort_rows(state["rows"], col, sort_state["desc"])
        for cid, *_ in COLUMNS:
            base = dict((c[0], c[1]) for c in COLUMNS)[cid]
            tree.heading(cid, text=base)
        base = dict((c[0], c[1]) for c in COLUMNS)[col]
        tree.heading(col, text=base + (" ↓" if sort_state["desc"] else " ↑"))
        render()

    var_search.trace_add("write", lambda *_: render())

    # ---------------- 详情弹窗 ----------------
    def show_detail(_event=None):
        sel = tree.focus()
        if not sel:
            return
        code = tree.item(sel, "values")[0]
        row = next((r for r in state["rows"] if r["code"] == code), None)
        if not row:
            return
        win = tk.Toplevel(root)
        win.title("详情 - {} {}".format(row["code"], row["name"]))
        win.geometry("420x300")
        info = "\n".join([
            "代码: {}".format(row["code"]),
            "名称: {}".format(row["name"]),
            "现价: {}".format(fmt_price(row["price"])),
            "最新净值: {}（{}）".format(fmt_price(row["nav"]), row["nav_date"]),
            "估算净值: {}（{}）".format(
                fmt_price(row["gsz"]) if row["gsz"] else "无估值", row["gztime"] or ""),
            "净值溢价: {}".format(fmt_pct(row["prem_nav"])),
            "估算溢价: {}".format(fmt_pct(row["prem_est"])),
            "三日均溢: {}".format(fmt_pct(row["prem3"])),
            "成交额: {}".format(fmt_amount(row["amount"])),
            "预计收益率(万元): {} / {:,.0f}元".format(
                fmt_pct(row["exp_ret"]),
                row["exp_amt"] if row["exp_amt"] is not None else 0),
            "申购状态: {}".format(row["sgzt"] or "未知"),
            "赎回状态: {}".format(row["shzt"] or "未知"),
        ])
        ttk.Label(win, text=info, justify="left",
                  font=("Consolas", 10)).pack(padx=14, pady=12, anchor="w")
        ttk.Button(win, text="打开东财行情页",
                   command=lambda: webbrowser.open(
                       "https://quote.eastmoney.com/{}.html".format(row["code"]))
                   ).pack(pady=4)

    tree.bind("<Double-1>", show_detail)

    # ---------------- 刷新 ----------------
    def worker():
        try:
            q.put(("status", "正在获取 LOF 列表 ..."))
            spot = fetch_lof_spot()
            if not spot:
                q.put(("error", "未获取到 LOF 列表，请检查网络"))
                return
            spot.sort(key=lambda x: -(x["amount"] or 0))

            def prog(d, t):
                q.put(("progress", d, t))

            q.put(("total", len(spot)))
            rows = compute_rows(spot, progress=prog)
            q.put(("rows", rows))
        except Exception as e:
            q.put(("error", "刷新失败: {}".format(e)))

    def refresh():
        if state["refreshing"]:
            return
        state["refreshing"] = True
        btn.config(state="disabled")
        pb.config(value=0)
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            while True:
                msg = q.get_nowait()
                kind = msg[0]
                if kind == "status":
                    status.config(text=msg[1])
                elif kind == "total":
                    pb.config(maximum=msg[1])
                elif kind == "progress":
                    pb.config(value=msg[1])
                    status.config(text="拉取数据中 ... {}/{}".format(msg[1], msg[2]))
                elif kind == "rows":
                    state["rows"] = msg[1]
                    state["rows"] = sort_rows(state["rows"], sort_state["col"],
                                              sort_state["desc"])
                    render()
                    status.config(text="完成：共 {} 只  ·  {}".format(
                        len(msg[1]), sort_tip()))
                    state["refreshing"] = False
                    btn.config(state="normal")
                elif kind == "error":
                    state["refreshing"] = False
                    btn.config(state="normal")
                    messagebox.showerror("错误", msg[1])
                    status.config(text=msg[1])
        except queue.Empty:
            pass
        # 自动刷新调度
        if state["after_id"]:
            root.after_cancel(state["after_id"])
            state["after_id"] = None
        if var_auto.get() and not state["refreshing"]:
            state["after_id"] = root.after(
                max(15, int(var_interval.get() or 60)) * 1000, refresh)
        root.after(300, poll)

    poll()
    refresh()  # 启动即拉取
    root.mainloop()


# ----------------------------------------------------------------------
# 命令行模式
# ----------------------------------------------------------------------

def run_cli():
    print("正在拉取全部 A 股 LOF 行情与净值 ...")
    spot = fetch_lof_spot()
    spot.sort(key=lambda x: -(x["amount"] or 0))
    print("共 {} 只 LOF".format(len(spot)))
    rows = compute_rows(spot)
    rows = sort_rows(rows, "prem", True)
    head = ["代码", "名称", "现价", "净值", "估算净值", "溢价/估算",
            "三日均溢", "成交额", "预计收益率", "预计收益额"]
    print("{:<8}{:<16}{:>8}{:>9}{:>9}{:>16}{:>9}{:>10}{:>10}{:>10}".format(*head))
    for r in rows[:50]:
        print("{:<8}{:<16}{:>8}{:>9}{:>9}{:>16}{:>9}{:>10}{:>10}{:>10}".format(
            r["code"], r["name"][:14], fmt_price(r["price"]), fmt_price(r["nav"]),
            fmt_price(r["gsz"]) if r["gsz"] else "--",
            "{}/{}".format(fmt_pct(r["prem_nav"]), fmt_pct(r["prem_est"])),
            fmt_pct(r["prem3"]), fmt_amount(r["amount"]),
            fmt_pct(r["exp_ret"]),
            "{:,.0f}".format(r["exp_amt"]) if r["exp_amt"] is not None else "--"))


if __name__ == "__main__":
    if "--cli" in sys.argv:
        run_cli()
    else:
        run_gui()
