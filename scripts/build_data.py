#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
土場邊坡監測 — 靜態資料產生器
================================
從三個外部來源抓資料,輸出 data/*.json 給前端 (GitHub Pages) 使用。
完全不依賴原本那台伺服器或本地 MySQL。

  GNSS 位移   rmdgnss.com (遠端 MySQL)  -> data/gnss.json
  時雨量      CODIS 歷史 CSV + CWA API  -> data/rainfall_hourly.json
  日雨量      由時雨量彙總              -> data/rainfall.json
  地震        USGS API                 -> data/earthquake.json
  摘要卡片                              -> data/summary.json

機密資訊一律由環境變數提供 (GitHub Secrets),不寫進程式碼:
  RMDGNSS_HOST (預設 rmdgnss.com) / RMDGNSS_USER (預設 ncu) /
  RMDGNSS_PASSWORD (必填才會抓 GNSS) / RMDGNSS_DB (預設 tuchang)
  CWA_API_KEY (必填才會抓即時雨量;歷史雨量仍會從 CSV 產生)

用法:
  python scripts/build_data.py
"""
import os
import sys
import json
import csv
import re
import math
import ssl
from datetime import datetime, timedelta, date, timezone
from urllib.request import urlopen, Request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, 'data')
RAIN_HOURLY_DIR = os.path.join(BASE, '土場雨量資料', '白蘭_時雨量')

# 土場 GNSS 站座標 (估算地震震度用)
SITE_LAT = 24.9648
SITE_LON = 121.1929

# 台北時區 (GitHub Actions runner 是 UTC,要固定換算成台灣時間)
TAIPEI = timezone(timedelta(hours=8))


def log(*a):
    print(*a, flush=True)


def write_json(name, obj):
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    n = len(obj) if isinstance(obj, list) else '—'
    log(f"  [OK] {name}  ({n} 筆)")


# ======================================================================
# GNSS —— 從 rmdgnss.com 抓原始資料算日平均 (含 HMove 跳階校正)
# ======================================================================
GNSS_FIELDS = ['E', 'N', 'H', 'Angle', 'Axis', 'Plate',
               'EMove', 'NMove', 'HMove', 'TotalMove', 'EDay', 'NDay', 'HDay']

# 2025-09-13 起儀器 HMove 跳階 -22mm,補回平移量 (與原伺服器 backfill 算法一致)
HMOVE_OFFSET_MM = 19.0
HMOVE_OFFSET_FROM = date(2025, 9, 13)


def build_gnss():
    log("GNSS: 連線 rmdgnss.com ...")
    pw = os.environ.get('RMDGNSS_PASSWORD')
    if not pw:
        log("  [略過] 未設定 RMDGNSS_PASSWORD 環境變數")
        return []
    try:
        import pymysql
    except ImportError:
        log("  [略過] 未安裝 pymysql")
        return []

    host = os.environ.get('RMDGNSS_HOST', 'rmdgnss.com')
    user = os.environ.get('RMDGNSS_USER', 'ncu')
    db = os.environ.get('RMDGNSS_DB', 'tuchang')

    conn = pymysql.connect(host=host, user=user, password=pw, database=db,
                           charset='utf8mb4', connect_timeout=30)
    try:
        avg_cols = ', '.join(f'ROUND(AVG(`{f}`),4) AS `{f}`' for f in GNSS_FIELDS)
        sql = (f"SELECT DATE(date_time) AS day, {avg_cols} FROM g1 "
               f"WHERE DATE(date_time) < CURDATE() "
               f"GROUP BY DATE(date_time) ORDER BY day")
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        conn.close()

    out = []
    for row in rows:
        day = row[0]
        vals = {GNSS_FIELDS[i]: (float(row[i + 1]) if row[i + 1] is not None else 0.0)
                for i in range(len(GNSS_FIELDS))}
        if day >= HMOVE_OFFSET_FROM:
            vals['HMove'] += HMOVE_OFFSET_MM
            vals['H'] += HMOVE_OFFSET_MM / 1000.0  # H 單位是公尺
            vals['TotalMove'] = round(
                (vals['EMove'] ** 2 + vals['NMove'] ** 2 + vals['HMove'] ** 2) ** 0.5, 4)
        item = {'date_time': datetime(day.year, day.month, day.day).strftime('%Y-%m-%d %H:%M:%S')}
        for f in GNSS_FIELDS:
            item[f] = round(vals[f], 4)
        out.append(item)

    write_json('gnss.json', out)
    return out


# ======================================================================
# 時雨量 —— CODIS 歷史 CSV 打底 + CWA API 續抓當前小時
# ======================================================================
def parse_codis_hourly():
    """讀取 土場雨量資料/白蘭_時雨量/*.csv,回傳 {datetime_str: precip}"""
    data = {}
    if not os.path.isdir(RAIN_HOURLY_DIR):
        log(f"  [警告] 找不到歷史時雨量資料夾: {RAIN_HOURLY_DIR}")
        return data
    for fn in sorted(os.listdir(RAIN_HOURLY_DIR)):
        if not fn.endswith('.csv') or 'Precipitation-hour' not in fn:
            continue
        m = re.search(r'(\d{4})-(\d{2})-Precipitation-hour', fn)
        if not m:
            continue
        year, month = int(m.group(1)), int(m.group(2))
        with open(os.path.join(RAIN_HOURLY_DIR, fn), encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            next(reader, None)  # 跳過表頭
            for row in reader:
                if not row or not row[0].strip().strip('"').isdigit():
                    continue
                day = int(row[0].strip().strip('"'))
                for h in range(1, 25):  # 第 1~24 欄 = 1~24 時
                    if h >= len(row):
                        break
                    v = row[h].strip().strip('"')
                    if v in ('&', '', 'X', 'x'):
                        continue  # 缺值
                    try:
                        precip = float(v)
                    except ValueError:
                        continue
                    try:
                        if h == 24:
                            dt = datetime(year, month, day) + timedelta(days=1)  # 24時 = 隔日 00:00
                        else:
                            dt = datetime(year, month, day, h)
                    except ValueError:
                        continue  # 無效日期 (如 2月30日)
                    data[dt.strftime('%Y-%m-%d %H:%M:%S')] = precip
    return data


def load_existing_hourly():
    """讀取先前 commit 的 rainfall_hourly.json (CSV 涵蓋範圍之後累積的資料)"""
    path = os.path.join(DATA_DIR, 'rainfall_hourly.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            arr = json.load(f)
        return {r['date_time']: r['precipitation'] for r in arr}
    except Exception as e:
        log(f"  [警告] 讀取現有 rainfall_hourly.json 失敗: {e}")
        return {}


def fetch_cwa_current():
    """從 CWA O-A0002-001 抓白蘭站 Past1hr 時雨量。回傳 (datetime_str, precip) 或 None。"""
    key = os.environ.get('CWA_API_KEY')
    if not key:
        log("  [略過即時雨量] 未設定 CWA_API_KEY (歷史雨量仍會產生)")
        return None
    url = ('https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0002-001'
           f'?Authorization={key}&format=JSON&StationName=%E7%99%BD%E8%98%AD')
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=30, context=ctx) as resp:
            d = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        log(f"  [警告] CWA API 失敗: {e}")
        return None
    stations = d.get('records', {}).get('Station', [])
    if not stations:
        log("  [警告] CWA 無白蘭站資料")
        return None
    st = stations[0]
    obs = st.get('ObsTime', {}).get('DateTime', '')
    try:
        past1 = float(st.get('RainfallElement', {}).get('Past1hr', {}).get('Precipitation', 0) or 0)
    except (ValueError, TypeError):
        return None
    if past1 < 0:
        return None  # CWA 用負數表示缺測/儀器異常
    if obs:
        odt = datetime.fromisoformat(obs).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    else:
        odt = datetime.now(TAIPEI).replace(minute=0, second=0, microsecond=0, tzinfo=None)
    return odt.strftime('%Y-%m-%d %H:%M:%S'), past1


def build_rainfall():
    log("雨量: 讀取 CODIS 歷史 CSV ...")
    merged = parse_codis_hourly()
    log(f"  CSV 歷史時雨量: {len(merged)} 筆")
    # 疊上先前累積 (CSV 涵蓋範圍之後的小時,以 json 為準)
    merged.update(load_existing_hourly())
    # 續抓當前小時
    cur = fetch_cwa_current()
    if cur:
        merged[cur[0]] = cur[1]
        log(f"  CWA 當前: {cur[0]} = {cur[1]} mm")

    hourly = [{'date_time': k, 'precipitation': round(v, 2)} for k, v in sorted(merged.items())]
    write_json('rainfall_hourly.json', hourly)

    # 日雨量 = 每日時雨量加總 (由時雨量彙總)
    daily = {}
    for k, v in merged.items():
        d = k[:10]
        daily[d] = daily.get(d, 0.0) + v
    daily_items = [{'date_time': d + ' 00:00:00', 'precipitation': round(val, 1)}
                   for d, val in sorted(daily.items())]
    write_json('rainfall.json', daily_items)
    return hourly


# ======================================================================
# 地震 —— USGS API,篩選會影響土場的事件
# ======================================================================
def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def build_earthquake():
    log("地震: 抓取 USGS API ...")
    start = '2024-07-01'
    end = (datetime.now(TAIPEI).date() + timedelta(days=1)).strftime('%Y-%m-%d')
    url = ('https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson'
           f'&starttime={start}&endtime={end}'
           '&minlatitude=22&maxlatitude=26&minlongitude=119&maxlongitude=123.5'
           '&minmagnitude=4')
    try:
        req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        log(f"  [警告] USGS API 失敗: {e}")
        # 保留現有檔案不覆蓋
        path = os.path.join(DATA_DIR, 'earthquake.json')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        write_json('earthquake.json', [])
        return []

    out = []
    for f in d.get('features', []):
        props = f.get('properties', {})
        coords = f.get('geometry', {}).get('coordinates', [None, None, None])
        lon, lat, depth = coords[0], coords[1], coords[2]
        if lon is None or lat is None:
            continue
        mag = props.get('mag') or 0
        place = props.get('place') or ''
        t = props.get('time', 0)
        dt = datetime.fromtimestamp(t / 1000, TAIPEI)  # 換算台灣時間
        dist = haversine(SITE_LAT, SITE_LON, lat, lon)
        if dist <= 100 or (mag >= 5.5 and dist <= 200):
            out.append({
                'date_time': dt.strftime('%Y-%m-%d %H:%M:%S'),
                'magnitude': round(float(mag), 1),
                'depth_km': round(float(depth), 1) if depth is not None else 0.0,
                'place': place,
                'distance_km': round(dist, 1),
            })
    out.sort(key=lambda x: x['date_time'])
    write_json('earthquake.json', out)
    return out


# ======================================================================
# 摘要卡片 —— 對應原本 /api/summary/ 的格式
# ======================================================================
SUMMARY_CONFIG = {
    'gnss': {
        'time_field': 'date_time',
        'cards': [
            {'title': 'GNSS 總位移', 'field': 'TotalMove', 'unit': ' mm', 'cls': 'ok'},
            {'title': 'GNSS 高程 H', 'field': 'H', 'unit': ' m', 'cls': '', 'decimals': 3},
        ],
    },
}


def build_summary(datasets):
    log("摘要: 產生 summary.json ...")
    result = {}
    for key, cfg in SUMMARY_CONFIG.items():
        data = datasets.get(key) or []
        tf = cfg['time_field']
        if data:
            last = data[-1]
            latest = {}
            for card in cfg['cards']:
                val = last.get(card['field'])
                if val is not None:
                    dec = card.get('decimals')
                    latest[card['field']] = round(float(val), dec) if dec else float(val)
            latest[tf] = last.get(tf)
        else:
            latest = None
        result[key] = {
            'count': len(data),
            'latest': latest,
            'time_field': tf,
            'summary_cards': cfg['cards'],
        }
    write_json('summary.json', result)


# ======================================================================
def main():
    # 可指定只更新哪些項目 (預設全部)。用於混合架構:
    #   GitHub Actions (國外 IP,連不到 rmdgnss) 只跑 rainfall + earthquake:
    #       python build_data.py rainfall earthquake
    #   台灣網路的電腦每天跑 GNSS:
    #       python build_data.py gnss
    all_targets = ['gnss', 'rainfall', 'earthquake']
    targets = [a.lower() for a in sys.argv[1:] if a.lower() in all_targets] or all_targets
    builders = {'gnss': build_gnss, 'rainfall': build_rainfall, 'earthquake': build_earthquake}

    log("=" * 56)
    log(f"土場邊坡監測 資料更新  {datetime.now(TAIPEI).strftime('%Y-%m-%d %H:%M:%S')} (台灣時間)")
    log(f"本次更新項目: {', '.join(targets)}")
    log("=" * 56)

    datasets = {}
    errors = []
    for name in all_targets:
        if name not in targets:
            continue
        try:
            datasets[name] = builders[name]()
        except Exception as e:
            errors.append(f"{name}: {e}")
            log(f"  [錯誤] {name}: {e}")

    # summary 依賴 gnss:只有這次成功抓到 gnss 才更新,避免把好的 summary 洗成空的
    if 'gnss' in targets and 'gnss' in datasets:
        try:
            build_summary(datasets)
        except Exception as e:
            errors.append(f"summary: {e}")
            log(f"  [錯誤] summary: {e}")

    log("=" * 56)
    if errors:
        log("完成 (有警告/錯誤):")
        for e in errors:
            log("  - " + e)
        # GNSS 失敗才視為致命 (雨量/地震失敗會保留舊資料,不讓排程變紅)
        if any(e.startswith('gnss') for e in errors):
            sys.exit(1)
    else:
        log("全部完成 [OK]")


if __name__ == '__main__':
    main()
