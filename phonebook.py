"""TSIS 1: PhoneBook - extended contact management (console app).

Features: multiple phones per contact, email, birthday, groups, filtering,
searching, sorting, paginated navigation, JSON export/import, extended CSV import.
Heavy lifting (add_phone, move_to_group, search_contacts, pagination) lives in the DB.
"""
import csv
import json
from contextlib import contextmanager
from datetime import datetime

import psycopg2

from config import PAGE_SIZE, PAGINATION_FUNCTION
from connect import get_connection

PHONE_TYPES = ("home", "work", "mobile")
DEFAULT_GROUP = "Other"

# Whitelist: menu choice -> (label, ORDER BY clause). Never build ORDER BY from raw input.
SORT_OPTIONS = {
    "1": ("name", "name ASC"),
    "2": ("birthday", "birthday ASC NULLS LAST, name ASC"),
    "3": ("date added", "created_at ASC, id ASC"),
}

HEADERS = ["ID", "Name", "Email", "Birthday", "Group", "Phones", "Added"]


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #
@contextmanager
def db():
    """Cursor with commit on success / rollback on error, connection always closed."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch(sql, params=()):
    with db() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# --------------------------------------------------------------------------- #
# Output / input helpers
# --------------------------------------------------------------------------- #
def print_table(rows):
    """rows: (id, name, email, birthday, group_name, phones, created_at)"""
    if not rows:
        print("  (nothing found)")
        return
    table = []
    for r in rows:
        table.append([
            str(r[0]),
            r[1],
            r[2] or "-",
            r[3].isoformat() if r[3] else "-",
            r[4] or "-",
            r[5] or "-",
            r[6].strftime("%Y-%m-%d") if r[6] else "-",
        ])
    widths = [max(len(HEADERS[i]), *(len(row[i]) for row in table)) for i in range(len(HEADERS))]
    line = "  ".join(h.ljust(w) for h, w in zip(HEADERS, widths))
    print(line)
    print("-" * len(line))
    for row in table:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))


def ask(prompt):
    return input(prompt).strip()


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def ask_date(prompt):
    while True:
        value = ask(prompt)
        if not value:
            return None
        try:
            return parse_date(value)
        except ValueError:
            print("  Wrong format, use YYYY-MM-DD (or leave empty).")


def ask_phone_type():
    while True:
        value = ask(f"  Type ({'/'.join(PHONE_TYPES)}) [mobile]: ").lower() or "mobile"
        if value in PHONE_TYPES:
            return value
        print("  Unknown type.")


def ask_group(prompt, allow_empty=True):
    groups = [r[0] for r in fetch("SELECT name FROM groups ORDER BY id")]
    print("  Groups: " + ", ".join(f"{i}) {g}" for i, g in enumerate(groups, 1)))
    value = ask(prompt)
    if not value:
        return None if allow_empty else DEFAULT_GROUP
    if value.isdigit() and 1 <= int(value) <= len(groups):
        return groups[int(value) - 1]
    return value


def ask_sort():
    print("  Sort by: " + ", ".join(f"{k}) {v[0]}" for k, v in SORT_OPTIONS.items()))
    choice = ask("  Choice [1]: ") or "1"
    return SORT_OPTIONS.get(choice, SORT_OPTIONS["1"])[1]


# --------------------------------------------------------------------------- #
# 3.2 Console search / filter / sort / pagination
# --------------------------------------------------------------------------- #
def show_all():
    order = ask_sort()
    print_table(fetch(f"SELECT * FROM contacts_full ORDER BY {order}"))


def filter_by_group():
    group = ask_group("Group (name or number): ")
    if not group:
        return
    order = ask_sort()
    rows = fetch(f"SELECT * FROM contacts_full WHERE group_name = %s ORDER BY {order}", (group,))
    print_table(rows)


def search_by_email():
    query = ask("Email (partial, e.g. gmail): ")
    if not query:
        return
    rows = fetch("SELECT * FROM contacts_full WHERE email ILIKE %s ORDER BY name", (f"%{query}%",))
    print_table(rows)


def search_all():
    query = ask("Search (name / email / phone / group / birthday): ")
    if not query:
        return
    print_table(fetch("SELECT * FROM search_contacts(%s)", (query,)))


def browse_pages():
    """Console loop over the existing DB pagination function."""

    def load(page):
        return fetch(f"SELECT * FROM {PAGINATION_FUNCTION}(%s, %s)", (PAGE_SIZE, page * PAGE_SIZE))

    page = 0
    rows = load(page)
    while True:
        print(f"\n--- Page {page + 1} ---")
        print_table(rows)
        cmd = ask("[next / prev / quit]: ").lower()
        if cmd in ("quit", "q"):
            return
        if cmd in ("next", "n"):
            nxt = load(page + 1)
            if nxt:
                page, rows = page + 1, nxt
            else:
                print("  This is the last page.")
        elif cmd in ("prev", "p"):
            if page == 0:
                print("  This is the first page.")
            else:
                page -= 1
                rows = load(page)
        else:
            print("  Type next, prev or quit.")


# --------------------------------------------------------------------------- #
# Create / modify
# --------------------------------------------------------------------------- #
def add_contact():
    name = ask("Name: ")
    if not name:
        print("  Name is required.")
        return
    if fetch("SELECT 1 FROM contacts WHERE name = %s", (name,)):
        print("  Contact already exists. Use 'Add phone' to add numbers to it.")
        return
    email = ask("Email (optional): ") or None
    if email and "@" not in email:
        print("  Email looks wrong.")
        return
    birthday = ask_date("Birthday YYYY-MM-DD (optional): ")
    group = ask_group(f"Group [{DEFAULT_GROUP}]: ", allow_empty=False)

    phones = []
    while True:
        phone = ask("Phone (empty to finish): ")
        if not phone:
            break
        phones.append((phone, ask_phone_type()))

    with db() as cur:
        cur.execute(
            "INSERT INTO contacts (name, email, birthday) VALUES (%s, %s, %s)",
            (name, email, birthday),
        )
        cur.execute("CALL move_to_group(%s, %s)", (name, group))
        for phone, ptype in phones:
            cur.execute("CALL add_phone(%s, %s, %s)", (name, phone, ptype))
    print("  Contact added.")


def add_phone_cmd():
    name = ask("Contact name: ")
    phone = ask("New phone: ")
    if not name or not phone:
        print("  Name and phone are required.")
        return
    ptype = ask_phone_type()
    with db() as cur:
        cur.execute("CALL add_phone(%s, %s, %s)", (name, phone, ptype))
    print("  Phone saved.")


def move_group_cmd():
    name = ask("Contact name: ")
    group = ask_group("Target group (name or number, new names are created): ")
    if not name or not group:
        print("  Name and group are required.")
        return
    with db() as cur:
        cur.execute("CALL move_to_group(%s, %s)", (name, group))
    print("  Contact moved.")


# --------------------------------------------------------------------------- #
# 3.3 Import / Export
# --------------------------------------------------------------------------- #
def export_json():
    path = ask("Output file [contacts.json]: ") or "contacts.json"
    with db() as cur:
        cur.execute(
            """SELECT c.id, c.name, c.email, c.birthday, g.name
               FROM contacts c LEFT JOIN groups g ON g.id = c.group_id
               ORDER BY c.name"""
        )
        contacts = cur.fetchall()
        cur.execute("SELECT contact_id, phone, type FROM phones ORDER BY id")
        phones = {}
        for cid, phone, ptype in cur.fetchall():
            phones.setdefault(cid, []).append({"phone": phone, "type": ptype})

    data = [
        {
            "name": name,
            "email": email,
            "birthday": birthday.isoformat() if birthday else None,
            "group": group,
            "phones": phones.get(cid, []),
        }
        for cid, name, email, birthday, group in contacts
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  Exported {len(data)} contacts to {path}")


def clean_contact(raw):
    """Validate one contact dict (from JSON or CSV). Raises ValueError on bad data."""
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("empty name")

    email = str(raw.get("email") or "").strip() or None
    if email and "@" not in email:
        raise ValueError(f"bad email '{email}'")

    birthday = None
    if raw.get("birthday"):
        try:
            birthday = parse_date(str(raw["birthday"]).strip())
        except ValueError:
            raise ValueError(f"bad birthday '{raw['birthday']}' (need YYYY-MM-DD)")

    phones = []
    for p in raw.get("phones") or []:
        phone = str(p.get("phone") or "").strip()
        ptype = str(p.get("type") or "mobile").strip().lower()
        if not phone:
            continue
        if ptype not in PHONE_TYPES:
            raise ValueError(f"bad phone type '{ptype}'")
        phones.append({"phone": phone, "type": ptype})

    group = str(raw.get("group") or "").strip() or None
    return {"name": name, "email": email, "birthday": birthday, "group": group, "phones": phones}


def save_contact(cur, c, overwrite):
    """Insert a new contact, or (overwrite=True) replace data of an existing one."""
    cur.execute("SELECT id FROM contacts WHERE name = %s", (c["name"],))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO contacts (name, email, birthday) VALUES (%s, %s, %s)",
            (c["name"], c["email"], c["birthday"]),
        )
        group = c["group"] or DEFAULT_GROUP
    else:
        group = c["group"]
        if overwrite:
            cur.execute(
                "UPDATE contacts SET email = %s, birthday = %s WHERE id = %s",
                (c["email"], c["birthday"], row[0]),
            )
            cur.execute("DELETE FROM phones WHERE contact_id = %s", (row[0],))
    if group:
        cur.execute("CALL move_to_group(%s, %s)", (c["name"], group))
    for p in c["phones"]:
        cur.execute("CALL add_phone(%s, %s, %s)", (c["name"], p["phone"], p["type"]))


def import_contacts(raw_list):
    """Shared by JSON and CSV import. On duplicate name asks: skip or overwrite."""
    policy = None  # "skip" / "overwrite" once the user chose "all"
    added = overwritten = skipped = failed = 0

    for raw in raw_list:
        try:
            c = clean_contact(raw)
        except ValueError as e:
            print(f"  ! {raw.get('name') or '?'}: {e} - skipped")
            failed += 1
            continue

        exists = bool(fetch("SELECT 1 FROM contacts WHERE name = %s", (c["name"],)))
        overwrite = False
        if exists:
            action = policy
            while action is None:
                ans = ask(
                    f"  '{c['name']}' already exists: [s]kip / [o]verwrite / "
                    "skip [a]ll / overwrite a[l]l: "
                ).lower()
                if ans == "a":
                    policy = action = "skip"
                elif ans == "l":
                    policy = action = "overwrite"
                elif ans in ("s", "skip"):
                    action = "skip"
                elif ans in ("o", "overwrite"):
                    action = "overwrite"
            if action == "skip":
                skipped += 1
                continue
            overwrite = True

        try:
            with db() as cur:
                save_contact(cur, c, overwrite)
        except psycopg2.Error as e:
            print(f"  ! {c['name']}: {str(e).strip().splitlines()[0]}")
            failed += 1
            continue
        if overwrite:
            overwritten += 1
        else:
            added += 1

    print(f"  Done: {added} added, {overwritten} overwritten, {skipped} skipped, {failed} failed.")


def import_json():
    path = ask("JSON file [contacts.json]: ") or "contacts.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  Cannot read file: {e}")
        return
    if not isinstance(data, list):
        print("  JSON must be a list of contacts.")
        return
    import_contacts(data)


def import_csv():
    """CSV columns: name,email,birthday,group,phone,phone_type
    One row per phone; rows with the same name are merged into one contact."""
    path = ask("CSV file [contacts.csv]: ") or "contacts.csv"
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        print(f"  Cannot read file: {e}")
        return

    grouped = {}
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        c = grouped.setdefault(
            name, {"name": name, "email": None, "birthday": None, "group": None, "phones": []}
        )
        for field in ("email", "birthday", "group"):
            value = (row.get(field) or "").strip()
            if value and not c[field]:
                c[field] = value
        phone = (row.get("phone") or "").strip()
        if phone:
            c["phones"].append({"phone": phone, "type": (row.get("phone_type") or "mobile")})
    import_contacts(list(grouped.values()))


# --------------------------------------------------------------------------- #
# Menu
# --------------------------------------------------------------------------- #
MENU = """
===== PhoneBook =====
 1. Show all contacts (sortable)
 2. Filter by group
 3. Search by email
 4. Search everywhere (name/email/phones/group/birthday)
 5. Browse pages (next / prev / quit)
 6. Add contact
 7. Add phone to contact
 8. Move contact to group
 9. Export to JSON
10. Import from JSON
11. Import from CSV
 0. Exit"""

ACTIONS = {
    "1": show_all,
    "2": filter_by_group,
    "3": search_by_email,
    "4": search_all,
    "5": browse_pages,
    "6": add_contact,
    "7": add_phone_cmd,
    "8": move_group_cmd,
    "9": export_json,
    "10": import_json,
    "11": import_csv,
}


def main():
    while True:
        print(MENU)
        choice = ask("> ")
        if choice == "0":
            print("Bye.")
            return
        action = ACTIONS.get(choice)
        if action is None:
            print("Unknown option.")
            continue
        try:
            action()
        except psycopg2.Error as e:
            # RAISE EXCEPTION from procedures arrives here as a readable message
            print(f"  DB error: {str(e).strip().splitlines()[0]}")
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")


if __name__ == "__main__":
    main()
