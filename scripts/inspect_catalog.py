"""Read-only inspection of the local SQLite copy of the export.

Prints only schema, counts and aggregates. Never dumps full rows of content.

Usage:
  python -I -X utf8 scripts/inspect_catalog.py <db> schema
  python -I -X utf8 scripts/inspect_catalog.py <db> profile <table> [top_n]
  python -I -X utf8 scripts/inspect_catalog.py <db> sql "<select ...>" [limit] [attach_db]

With attach_db the second database is attached read-only under the schema name `sig`.
Quote identifiers with [brackets]; PowerShell strips double quotes from native arguments.
"""

import sqlite3
import sys


def connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def q(cur, sql, params=()):
    return cur.execute(sql, params).fetchall()


def schema(cur):
    tables = [r[0] for r in q(cur, "select name from sqlite_master where type='table' order by name")]
    for t in tables:
        n = q(cur, f'select count(*) from "{t}"')[0][0]
        cols = q(cur, f'pragma table_info("{t}")')
        col_desc = ", ".join(f"{c[1]}:{c[2] or '?'}" + ("*" if c[5] else "") for c in cols)
        print(f"{t} ({n}): {col_desc}")


def profile(cur, table, top_n=12):
    n = q(cur, f'select count(*) from "{table}"')[0][0]
    cols = q(cur, f'pragma table_info("{table}")')
    print(f"## {table}: {n} rows, {len(cols)} columns")
    for c in cols:
        name = c[1]
        nulls = q(cur, f'select count(*) from "{table}" where "{name}" is null')[0][0]
        distinct = q(cur, f'select count(distinct "{name}") from "{table}"')[0][0]
        line = f"- {name} ({c[2] or '?'}): null={nulls}, distinct={distinct}"
        if distinct <= top_n and distinct > 0:
            vals = q(
                cur,
                f'select "{name}", count(*) as c from "{table}" group by "{name}" order by c desc limit {top_n}',
            )
            line += " values=" + "; ".join(f"{v!r}:{cnt}" for v, cnt in vals)
        else:
            mm = q(cur, f'select min("{name}"), max("{name}") from "{table}"')[0]
            line += f" min={mm[0]!r} max={mm[1]!r}"
        print(line)


def run_sql(cur, sql, limit=60):
    rows = q(cur, sql)
    for r in rows[:limit]:
        print(" | ".join("" if v is None else str(v) for v in r))
    if len(rows) > limit:
        print(f"... ({len(rows)} rows total, showing {limit})")
    else:
        print(f"({len(rows)} rows)")


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    path, cmd = argv[1], argv[2]
    con = connect(path)
    cur = con.cursor()
    if cmd == "schema":
        schema(cur)
    elif cmd == "profile":
        profile(cur, argv[3], int(argv[4]) if len(argv) > 4 else 12)
    elif cmd == "sql":
        sql = argv[3]
        if not sql.strip().lower().startswith(("select", "with", "pragma")):
            print("only read queries are allowed")
            return 2
        if len(argv) > 5:
            cur.execute("attach database ? as sig", (f"file:{argv[5]}?mode=ro",))
        run_sql(cur, sql, int(argv[4]) if len(argv) > 4 else 60)
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
