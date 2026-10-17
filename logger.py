"""
logger.py — epizodik hafiza yazicisi. pairs.json'daki pariteleri 60 sn'de bir
orneklor ve memory.db (SQLite) icindeki `snapshots` tablosuna yazar.

Tur basina tek `tickers SPOT` cagrisi (24s hacim) + parite basina bir
orderbook cagrisi. Basarisiz cekim de ok=0 ile YAZILIR; veri kesintisi
gorunur olsun (fail-closed icin bayatlik tespiti buna dayanir).
Kullanim: `python logger.py --once` | `--status` | argumansiz (sonsuz dongu).
"""

import json
import sqlite3
import sys
import time

import atk_client

DB_PATH = "memory.db"
PAIRS_PATH = "pairs.json"
INTERVAL_S = 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ts                   INTEGER NOT NULL,  -- unix saniye
    inst                 TEXT    NOT NULL,
    mid                  REAL,
    spread_bps           REAL,
    bid_depth_2pct_usdt  REAL,
    ask_depth_2pct_usdt  REAL,
    vol24h_usdt          REAL,
    covers_band          INTEGER,           -- 1/0/NULL
    ok                   INTEGER NOT NULL,  -- 1/0
    latency_ms           INTEGER,
    error                TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_inst_ts ON snapshots (inst, ts);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def load_pairs():
    with open(PAIRS_PATH) as f:
        return [r["inst"] for r in json.load(f)]


def run_round(conn, pairs):
    """Bir tur: hacimler + her parite icin tahta. Tek paritenin hatasi turu durdurmaz."""
    started = time.time()

    # Tur basina tek cagri: 24s hacimler
    tick = atk_client.get_tickers_spot()
    vol_by_inst = {}
    if tick["ok"]:
        vol_by_inst = {t["instId"]: float(t["volCcy24h"]) for t in tick["data"]}
    else:
        print(f"[uyari] tickers cekilemedi: {tick['error']}")

    rows, good, bad = [], 0, 0
    for inst in pairs:
        ts = int(time.time())
        ob = atk_client.get_orderbook(inst)
        dw = atk_client.depth_within(ob["data"]) if ob["ok"] else None

        if dw is None:
            bad += 1
            rows.append((ts, inst, None, None, None, None,
                         vol_by_inst.get(inst), None, 0,
                         ob["latency_ms"], ob["error"] or "tahta bos/bozuk"))
        else:
            good += 1
            rows.append((ts, inst, dw["mid"], dw["spread_bps"],
                         dw["bid_depth_usdt"], dw["ask_depth_usdt"],
                         vol_by_inst.get(inst), int(dw["covers_band"]), 1,
                         ob["latency_ms"], None))

    conn.executemany(
        "INSERT INTO snapshots (ts, inst, mid, spread_bps, bid_depth_2pct_usdt,"
        " ask_depth_2pct_usdt, vol24h_usdt, covers_band, ok, latency_ms, error)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()

    elapsed = time.time() - started
    print(f"[tur] {time.strftime('%H:%M:%S')} sure={elapsed:.1f}s "
          f"basarili={good} basarisiz={bad} satir={len(rows)}", flush=True)
    if elapsed > INTERVAL_S:
        print(f"[UYARI] tur {elapsed:.1f}s surdu, {INTERVAL_S}s araligi asildi",
              flush=True)
    return elapsed


def show_status(conn):
    now = int(time.time())
    q = """
    SELECT inst, COUNT(*), MAX(ts),
           ROUND(AVG(ok) * 100, 1)
    FROM snapshots GROUP BY inst ORDER BY inst
    """
    print(f"{'parite':<14} {'satir':>6} {'son_ts_yasi_sn':>15} {'ok_orani_%':>11}")
    total = 0
    for inst, cnt, last_ts, ok_rate in conn.execute(q):
        total += cnt
        print(f"{inst:<14} {cnt:>6} {now - last_ts:>15} {ok_rate:>11}")
    turns = conn.execute("SELECT COUNT(DISTINCT ts / 60) FROM snapshots").fetchone()[0]
    print(f"\ntoplam satir={total}  yaklasik tur sayisi={turns}")


def main():
    args = sys.argv[1:]
    conn = connect()

    if "--status" in args:
        show_status(conn)
        return

    pairs = load_pairs()
    print(f"{len(pairs)} parite yuklendi ({PAIRS_PATH})", flush=True)

    if "--once" in args:
        run_round(conn, pairs)
        return

    while True:
        elapsed = run_round(conn, pairs)
        time.sleep(max(0, INTERVAL_S - elapsed))


if __name__ == "__main__":
    main()
