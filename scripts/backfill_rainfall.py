#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
時雨量補洞工具 —— 從 CODIS 抓指定月份的白蘭站 (C1D410) 逐時雨量,
併進 data/rainfall_hourly.json,並重算 data/rainfall.json (日雨量)。

用途: 補上原伺服器壞掉時遺失、且 CSV 沒涵蓋到的月份。
需在「台灣/校園網路」的電腦上執行 (CODIS 可能擋國外 IP)。

用法:
  python scripts/backfill_rainfall.py 2026-05 2026-06 2026-07 2026-08
  (不給參數時,自動補「現有資料最後一筆」到「本月」之間所有月份)
"""
import os
import sys
import ssl
import json
import time
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, 'data')
HOURLY_JSON = os.path.join(DATA_DIR, 'rainfall_hourly.json')
DAILY_JSON = os.path.join(DATA_DIR, 'rainfall.json')

STATION = 'C1D410'
STN_TYPE = 'auto_C1'
API = 'https://codis.cwa.gov.tw/api/station'


def month_last_day(y, m):
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


def fetch_month(y, m):
    """抓 CODIS 一個月的逐時雨量,回傳 {'YYYY-MM-DD HH:MM:SS': precip}"""
    start = date(y, m, 1)
    end = month_last_day(y, m)
    payload = {
        'date': f'{start.isoformat()}T00:00:00.000+08:00',
        'type': 'report_date',      # 逐時報表
        'stn_ID': STATION,
        'stn_type': STN_TYPE,
        'start': f'{start.isoformat()}T00:00:00',
        'end': f'{end.isoformat()}T23:59:59',
    }
    data = urllib.parse.urlencode(payload).encode()
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(API, data=data, headers={
        'User-Agent': 'Mozilla/5.0',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'accept': 'application/json',
        'x-requested-with': 'XMLHttpRequest',
        'referer': 'https://codis.cwa.gov.tw/StationData',
    })
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        d = json.loads(r.read().decode('utf-8'))
    if d.get('code') != 200:
        raise RuntimeError(f"CODIS 回傳 code={d.get('code')} msg={d.get('message')}")
    out = {}
    rows = (d.get('data') or [{}])[0].get('dts', [])
    for row in rows:
        dt = row.get('DataTime')  # 'YYYY-MM-DDTHH:MM:SS'
        precip = (row.get('Precipitation') or {}).get('Accumulation')
        if dt and precip is not None and precip >= 0:
            out[dt.replace('T', ' ')] = float(precip)
    return out


def load_hourly():
    if not os.path.exists(HOURLY_JSON):
        return {}
    with open(HOURLY_JSON, encoding='utf-8') as f:
        return {r['date_time']: r['precipitation'] for r in json.load(f)}


def months_to_fetch(existing):
    """自動偵測: 從現有資料最後一筆的月份補到本月"""
    if existing:
        last = max(existing)
        y, m = int(last[:4]), int(last[5:7])
    else:
        y, m = 2024, 7
    today = date.today()
    out = []
    while (y, m) <= (today.year, today.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def main():
    args = sys.argv[1:]
    existing = load_hourly()
    print(f"現有時雨量: {len(existing)} 筆")

    if args:
        months = []
        for a in args:
            y, m = int(a[:4]), int(a[5:7])
            months.append((y, m))
    else:
        months = months_to_fetch(existing)

    print("將補抓月份:", ', '.join(f'{y}-{m:02d}' for y, m in months))
    added = 0
    for y, m in months:
        try:
            got = fetch_month(y, m)
            new = sum(1 for k in got if k not in existing)
            existing.update(got)
            added += new
            print(f"  {y}-{m:02d}: 抓到 {len(got)} 筆 (新增 {new})")
        except Exception as e:
            print(f"  {y}-{m:02d}: [失敗] {e}")
        time.sleep(1)

    # 寫回時雨量 (排序)
    hourly = [{'date_time': k, 'precipitation': round(v, 2)} for k, v in sorted(existing.items())]
    with open(HOURLY_JSON, 'w', encoding='utf-8') as f:
        json.dump(hourly, f, ensure_ascii=False, separators=(',', ':'))
    # 重算日雨量
    daily = {}
    for k, v in existing.items():
        daily[k[:10]] = daily.get(k[:10], 0.0) + v
    daily_items = [{'date_time': d + ' 00:00:00', 'precipitation': round(val, 1)}
                   for d, val in sorted(daily.items())]
    with open(DAILY_JSON, 'w', encoding='utf-8') as f:
        json.dump(daily_items, f, ensure_ascii=False, separators=(',', ':'))

    print(f"完成: 共新增 {added} 筆,rainfall_hourly.json 現有 {len(hourly)} 筆")
    if hourly:
        print(f"       範圍 {hourly[0]['date_time']} ~ {hourly[-1]['date_time']}")


if __name__ == '__main__':
    main()
