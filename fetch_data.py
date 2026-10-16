#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Action 定时任务：抓取全部 A 股 LOF 的净值数据 → data.json
由 .github/workflows/update-data.yml 每天多次调用，结果提交回仓库，
供 index.html 同源加载（不受访客网络限制）。
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://fund.eastmoney.com/",
}
SPOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

S = requests.Session()
S.headers.update(HEADERS)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_spot():
    rows = []
    pn = 1
    while pn <= 10:
        r = S.get(SPOT_URL, params={
            "pn": pn, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "fid": "f12", "fs": "b:MK0404,b:MK0405,b:MK0406,b:MK0407",
            "fields": "f12,f13,f14",
        }, timeout=20)
        data = r.json().get("data") or {}
        diff = data.get("diff") or []
        if not diff:
            break
        rows += [{"code": d["f12"], "mkt": d["f13"], "name": d["f14"]} for d in diff]
        if len(rows) >= int(data.get("total", 0)):
            break
        pn += 1
    return rows


def fetch_lsjz(code, size=8):
    """历史净值 + 申购/赎回状态"""
    try:
        r = S.get(LSJZ_URL, params={
            "fundCode": code, "pageIndex": 1, "pageSize": size,
        }, timeout=15)
        lst = (r.json().get("Data") or {}).get("LSJZList") or []
        out = []
        for it in lst:
            nav = _f(it.get("DWJZ"))
            if nav:
                out.append((it["FSRQ"], nav, it.get("SGZT") or "", it.get("SHZT") or ""))
        return out
    except Exception:
        return []


def fetch_kline(secid, lmt=8):
    try:
        r = S.get(KLINE_URL, params={
            "secid": secid, "klt": 101, "fqt": 0, "lmt": lmt, "end": "20500101",
            "fields1": "f1,f2,f3", "fields2": "f51,f53",
        }, timeout=15)
        kl = ((r.json().get("data") or {}).get("klines")) or []
        out = []
        for line in reversed(kl):
            p = line.split(",")
            c = _f(p[1])
            if c:
                out.append((p[0], c))
        return out
    except Exception:
        return []


def main():
    spot = fetch_spot()
    if not spot:
        print("ERROR: LOF 列表获取失败")
        sys.exit(1)
    print("LOF 总数:", len(spot))

    funds = {}

    def work(f):
        ls = fetch_lsjz(f["code"])
        kl = fetch_kline("{}.{}".format(f["mkt"], f["code"]))
        rec = {
            "name": f["name"], "mkt": f["mkt"],
            "nav": ls[0][1] if ls else None,
            "nav_date": ls[0][0] if ls else "",
            "prem3": None, "sgzt": ls[0][2] if ls else "", "shzt": ls[0][3] if ls else "",
        }
        # 三日均溢
        nav_by_date = {d: n for d, n, _, _ in ls}
        ps = [c / nav_by_date[d] - 1 for d, c in kl[:3] if nav_by_date.get(d)]
        if ps:
            rec["prem3"] = round(sum(ps) / len(ps), 6)
        return f["code"], rec

    with ThreadPoolExecutor(max_workers=20) as ex:
        futs = [ex.submit(work, f) for f in spot]
        for fu in as_completed(futs):
            try:
                code, rec = fu.result()
                funds[code] = rec
            except Exception as e:
                print("fail:", e)

    ok = sum(1 for v in funds.values() if v["nav"])
    print("净值获取成功: {}/{}".format(ok, len(funds)))
    if ok == 0:
        print("ERROR: 全部净值获取失败，不写文件")
        sys.exit(1)

    data = {
        "updated": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(funds),
        "funds": funds,
    }
    with open("data.json", "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, separators=(",", ":"))
    print("data.json 已生成")


if __name__ == "__main__":
    main()
