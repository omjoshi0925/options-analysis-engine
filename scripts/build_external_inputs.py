#!/usr/bin/env python
"""Build data/external/dividends.csv and data/external/splits.csv from the raw issuer files.

Raw inputs (retrieval details and hashes in data/external/PROVENANCE.md):
  data/external/raw/apple-dividend-history-table.html       Apple Investor Relations dividend history table
  data/external/raw/spdr-etf-historical-distributions.xlsx  State Street SPDR ETF historical distributions

Output columns: symbol, ex_date, amount. Amounts are as declared or paid on
each ex-date's own share basis (Apple states its amounts are not split
adjusted; SPY has never split). Apple publishes record dates, not ex-dates,
so each AAPL ex-date is taken from the DoltHub post-no-preference/stocks
`dividend` table row for the same distribution (the row whose ex_date falls
in the five days up to the issuer's record date); if no such row exists the
settlement rule is used instead (one XNYS session before the record date
before 2024-05-28, the record date itself under T+1) and the row is flagged.
Splits come from the issuer's split rows and are checked against the
DoltHub `split` table.

    python scripts/build_external_inputs.py [--start 2018-01-01] [--crosscheck other.csv]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT/"data/external/raw"
OUT = ROOT/"data/external"
T_PLUS_ONE_FROM = dt.date(2024, 5, 28)


def parse_date(text):
    text = html.unescape(text).replace("\xa0", " ").replace("*", "").strip()
    text = re.sub(r"\s*,\s*", ", ", text)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date {text!r}")


def previous_session(day):
    import exchange_calendars as xc
    calendar = xc.get_calendar("XNYS")
    return calendar.previous_session(day).date()


def apple_rows(path):
    """Yield (record_date, payable_date, amount or None, type) from the Apple table."""
    text = path.read_text()
    for row in re.findall(r"<tr>(.*?)</tr>", text, flags=re.S):
        cells = re.findall(r'<td data-heading="([^"]+)">(.*?)</td>', row, flags=re.S)
        if not cells:
            continue
        values = {key: html.unescape(re.sub(r"<[^>]+>", "", value)).replace("\xa0", " ").strip() for key, value in cells}
        amount = values["Amount"]
        yield (parse_date(values["Record"]), parse_date(values["Payable"]),
               None if amount == "N/A" else float(amount.replace("$", "")), values["Type"])


def dolt_ex_dates(path, symbol):
    return sorted(dt.date.fromisoformat(r["ex_date"]) for r in csv.DictReader(open(path)) if r["act_symbol"] == symbol)


def apple_dividends(path, start, dolt_path=RAW/"dolt-stocks-dividend-aapl-spy.csv"):
    """Rows with record dates from `start` on; the fallback ex-date rule needs the exchange calendar, which begins in 2006."""
    dividends, splits = [], []
    known = dolt_ex_dates(dolt_path, "AAPL") if dolt_path.exists() else []
    for record, payable, amount, kind in apple_rows(path):
        if record < start:
            continue
        if kind == "Regular Cash":
            matches = [d for d in known if record-dt.timedelta(days=5) <= d <= record]
            if len(matches) == 1:
                ex_date, source = matches[0], "dolt_dividend_table"
            else:
                ex_date = record if record >= T_PLUS_ONE_FROM else previous_session(record)
                source = "settlement_rule_fallback"
                print(f"  note: no DoltHub ex-date for AAPL record date {record}; used settlement rule -> {ex_date}")
            dividends.append(dict(symbol="AAPL", ex_date=ex_date, amount=amount, record_date=record, ex_date_source=source))
        elif "Stock Split" in kind:
            to, _for = re.match(r"(\d+)-for-(\d+)", kind).groups()
            # The payable column carries the first split-adjusted trading date (starred on the page).
            splits.append(dict(symbol="AAPL", ex_date=payable, to_factor=int(to), for_factor=int(_for)))
        else:
            raise ValueError(f"Unexpected row type {kind!r}")
    return dividends, splits


def xlsx_rows(path):
    main = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    book = zipfile.ZipFile(path)
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    targets = {r.get("Id"): r.get("Target") for r in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
    strings = ["".join(t.text or "" for t in si.iter(main+"t")) for si in ET.fromstring(book.read("xl/sharedStrings.xml"))]
    (name, target), = [(s.get("name"), targets[s.get(rel+"id")]) for s in workbook.find(main+"sheets")]
    header = None
    for row in ET.fromstring(book.read("xl/"+target)).iter(main+"row"):
        cells = {}
        for cell in row:
            column = re.match(r"[A-Z]+", cell.get("r")).group(0)
            value = cell.find(main+"v")
            if cell.get("t") == "s":
                cells[column] = strings[int(value.text)]
            elif cell.get("t") == "inlineStr":
                cells[column] = "".join(t.text or "" for t in cell.iter(main+"t"))
            else:
                cells[column] = value.text if value is not None else ""
        if header is None:
            header = cells
            continue
        yield {header[column]: cells.get(column, "").strip() for column in header}


def spy_dividends(path, start):
    rows = []
    for record in xlsx_rows(path):
        if record["TICKER"] != "SPY" or parse_date(record["EX-DATE"]) < start:
            continue
        gains = [record.get("SHORT TERM CAPITAL GAIN ($)", ""), record.get("LONG TERM CAPITAL GAIN ($)", "")]
        if any(g not in ("", "0", "0.000000") and float(g) != 0 for g in gains):
            raise ValueError(f"SPY row with a capital-gain distribution needs a decision: {record}")
        rows.append(dict(symbol="SPY", ex_date=parse_date(record["EX-DATE"]), amount=float(record["DIVIDEND ($)"]),
                         record_date=parse_date(record["RECORD DATE"]), ex_date_source="issuer_file"))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2018-01-01", help="keep ex-dates on or after this date")
    parser.add_argument("--crosscheck", help="CSV with act_symbol, ex_date, amount to compare against (report only)")
    args = parser.parse_args()
    start = dt.date.fromisoformat(args.start)
    aapl, splits = apple_dividends(RAW/"apple-dividend-history-table.html", start-dt.timedelta(days=7))
    spy = spy_dividends(RAW/"spdr-etf-historical-distributions.xlsx", start)
    rows = sorted((r for r in aapl+spy if r["ex_date"] >= start), key=lambda r: (r["symbol"], r["ex_date"]))
    with (OUT/"dividends.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["symbol", "ex_date", "amount"])
        for r in rows:
            writer.writerow([r["symbol"], r["ex_date"].isoformat(), f"{r['amount']:.6f}".rstrip("0").rstrip(".")])
    with (OUT/"splits.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["symbol", "ex_date", "to_factor", "for_factor"])
        for s in sorted(splits, key=lambda s: s["ex_date"]):
            if s["ex_date"] >= start:
                writer.writerow([s["symbol"], s["ex_date"].isoformat(), s["to_factor"], s["for_factor"]])
    print(f"wrote {len(rows)} dividend rows and {sum(s['ex_date'] >= start for s in splits)} split rows (ex-dates >= {start})")
    if args.crosscheck:
        other = {(r["act_symbol"], r["ex_date"]): float(r["amount"]) for r in csv.DictReader(open(args.crosscheck))}
        mine = {(r["symbol"], r["ex_date"].isoformat()): r["amount"] for r in rows}
        for key in sorted(set(mine) | {k for k in other if dt.date.fromisoformat(k[1]) >= start}):
            a, b = mine.get(key), other.get(key)
            if a is None or b is None or abs(a-b) > 1e-5:
                print(f"  crosscheck differs: {key} issuer={a} other={b}")
        print("crosscheck done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
