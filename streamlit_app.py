import os, sqlite3, secrets, hmac
from datetime import date, datetime
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Ashirvad Venue Booking", page_icon="📅", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DATABASE_PATH", str(BASE_DIR / "venue.db"))
CURRENCY = os.environ.get("CURRENCY", "₹")
SLOTS = ["Morning", "Evening", "Full day"]
METHODS = ["Cash", "UPI", "Bank transfer", "Card"]
PAY_DETAILS = []  # Configure verified organisation payment details before accepting payments.

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT);
CREATE TABLE IF NOT EXISTS venues(id INTEGER PRIMARY KEY, name TEXT, capacity INTEGER, base_price REAL, description TEXT);
CREATE TABLE IF NOT EXISTS options(id INTEGER PRIMARY KEY, name TEXT, price REAL, description TEXT);
CREATE TABLE IF NOT EXISTS bookings(id INTEGER PRIMARY KEY, venue_id INTEGER, client_name TEXT, phone TEXT,
  event_date TEXT, slot TEXT, guests INTEGER, total_amount REAL, notes TEXT,
  status TEXT DEFAULT 'active', created_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  email TEXT, source TEXT DEFAULT 'Walk-in', token TEXT);
CREATE TABLE IF NOT EXISTS booking_options(booking_id INTEGER, option_id INTEGER);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, booking_id INTEGER, amount REAL, paid_on TEXT,
  method TEXT, note TEXT, recorded_by TEXT, status TEXT DEFAULT 'confirmed', reference TEXT);
"""

def get_secret(name):
    try:
        return st.secrets.get(name, os.environ.get(name, ""))
    except (FileNotFoundError, KeyError):
        return os.environ.get(name, "")

def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = connect()
    con.executescript(SCHEMA)
    if con.execute("SELECT COUNT(*) FROM venues").fetchone()[0] == 0:
        con.executemany("INSERT INTO venues(name,capacity,base_price,description) VALUES(?,?,?,?)", [
            ("Grand Hall", 500, 60000, "Air-conditioned hall with stage and dining area."),
            ("Garden Lawn", 300, 40000, "Open lawn with a covered stage."),
            ("Mini Hall", 150, 20000, "Intimate hall for small functions.")])
        con.executemany("INSERT INTO options(name,price,description) VALUES(?,?,?)", [
            ("Catering package", 50000, "Vegetarian sadya for the booked guest count."),
            ("Stage decoration", 15000, "Flowers, backdrop and lamp setup."),
            ("Sound and lighting", 8000, "PA system, microphones and stage lights."),
            ("Photography", 20000, "Photo and video coverage."),
            ("Valet parking", 3000, "Parking staff for the event.")])
    # Migrate older databases if supplied
    for table, col, definition in [
        ("bookings","email","TEXT"), ("bookings","source","TEXT DEFAULT 'Walk-in'"),
        ("bookings","token","TEXT"), ("payments","status","TEXT DEFAULT 'confirmed'"),
        ("payments","reference","TEXT")]:
        cols = [r["name"] for r in con.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
    for row in con.execute("SELECT id FROM bookings WHERE token IS NULL").fetchall():
        con.execute("UPDATE bookings SET token=? WHERE id=?", (secrets.token_urlsafe(6), row["id"]))
    con.commit()
    con.close()

def rows(sql, params=()):
    con = connect()
    result = [dict(row) for row in con.execute(sql, params).fetchall()]
    con.close()
    return result

def execute(sql, params=()):
    con = connect()
    cur = con.execute(sql, params)
    con.commit()
    last = cur.lastrowid
    con.close()
    return last

def money(value):
    return f"{CURRENCY}{float(value or 0):,.2f}"

def taken(venue_id, day, slot, ignore_id=None):
    sql = "SELECT id,slot FROM bookings WHERE venue_id=? AND event_date=? AND status IN ('pending','active')"
    params = [venue_id, day.isoformat()]
    if ignore_id:
        sql += " AND id<>?"
        params.append(ignore_id)
    return any(r["slot"] == slot or "Full day" in (r["slot"], slot) for r in rows(sql, params))

def venues_options():
    return rows("SELECT * FROM venues ORDER BY id"), rows("SELECT * FROM options ORDER BY id")

def booking_total(venue, selected):
    extras = sum(float(o["price"]) for o in rows("SELECT * FROM options") if o["name"] in selected)
    return float(venue["base_price"]) + extras

def create_booking(venue_id, client_name, phone, email, event_day, slot, guests, notes,
                   selected_options, source, created_by, status="pending", total_override=None):
    venue = next((v for v in rows("SELECT * FROM venues") if v["id"] == venue_id), None)
    if not venue:
        return None, "Please select a valid venue."
    if not client_name.strip():
        return None, "Enter the client name."
    if not phone.strip() and source == "Online":
        return None, "Enter a phone number."
    if event_day < date.today() and source == "Online":
        return None, "Choose a date that is not in the past."
    if taken(venue_id, event_day, slot):
        return None, "That venue is already booked for this date and slot."
    opts = rows("SELECT * FROM options")
    chosen = [o for o in opts if o["name"] in selected_options]
    total = float(total_override) if total_override and float(total_override) > 0 else booking_total(venue, selected_options)
    token = secrets.token_urlsafe(6)
    bid = execute("""INSERT INTO bookings(venue_id,client_name,phone,email,event_date,slot,guests,total_amount,notes,status,source,token,created_by)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (venue_id, client_name.strip(), phone, email, event_day.isoformat(), slot, int(guests), total,
         notes, status, source, token, created_by))
    con = connect()
    con.executemany("INSERT INTO booking_options(booking_id,option_id) VALUES(?,?)", [(bid,o["id"]) for o in chosen])
    con.commit(); con.close()
    return (bid, token), None

def booking_detail(bid):
    result = rows("""SELECT b.*, v.name AS venue, v.capacity FROM bookings b
                     JOIN venues v ON v.id=b.venue_id WHERE b.id=?""", (bid,))
    return result[0] if result else None

def show_booking_form(staff=False):
    venues, opts = venues_options()
    if not venues:
        st.warning("No venues have been configured.")
        return
    if not staff:
        st.info("Customers can check the calendar, choose a venue/date/slot, select extra services and submit a booking request. Requests remain pending until staff approval.")
    with st.form("new_booking_form"):
        venue_names = {v["name"]: v for v in venues}
        venue_name = st.selectbox("Venue", list(venue_names))
        venue = venue_names[venue_name]
        st.caption(f"Capacity: {venue['capacity']} · Base price: {money(venue['base_price'])}")
        col1, col2 = st.columns(2)
        client = col1.text_input("Client name")
        phone = col2.text_input("Phone number")
        email = st.text_input("Email (optional)")
        col3, col4, col5 = st.columns(3)
        event_day = col3.date_input("Event date", min_value=date.today() if not staff else date(2000,1,1))
        slot = col4.selectbox("Time slot", SLOTS)
        guests = col5.number_input("Number of guests", min_value=1, max_value=10000, value=100)
        selected = st.multiselect("Additional services", [o["name"] for o in opts],
                                  format_func=lambda n: f"{n} — {money(next(o['price'] for o in opts if o['name']==n))}")
        notes = st.text_area("Notes / special requirements")
        source = st.selectbox("Booking source", ["Walk-in", "Phone", "Online"]) if staff else "Online"
        total_override = st.number_input("Total amount (0 = calculate automatically)", min_value=0.0, value=0.0) if staff else 0
        advance = st.number_input("Advance payment (optional)", min_value=0.0, value=0.0) if staff else 0
        method = st.selectbox("Advance payment method", METHODS) if staff else "Cash"
        submitted = st.form_submit_button("Submit booking request" if not staff else "Create booking", type="primary")
    if submitted:
        result, error = create_booking(venue["id"], client, phone, email, event_day, slot, guests,
                    notes, selected, source, st.session_state.get("staff_user","customer"),
                    "active" if staff else "pending", total_override if staff else None)
        if error:
            st.error(error)
        else:
            bid, token = result
            if staff and advance > 0:
                execute("""INSERT INTO payments(booking_id,amount,paid_on,method,note,recorded_by,status)
                           VALUES(?,?,?,?,?,?, 'confirmed')""",
                        (bid, advance, date.today().isoformat(), method, "Advance", st.session_state["staff_user"]))
            st.success(f"Booking created. Booking ID: {bid}. Tracking reference: {token}")
            st.info("Save this reference to track the booking." if not staff else "Open the Bookings page to manage it.")

def get_setting(key):
    value = os.environ.get(key)
    if value:
        return value
    try:
        return st.secrets.get(key)
    except (FileNotFoundError, KeyError):
        return None

def staff_login():
    st.subheader("Staff login")
    configured_user = get_setting("STAFF_USERNAME")
    configured_password = get_setting("STAFF_PASSWORD")
    if not configured_user or not configured_password:
        st.warning("Staff login is disabled until STAFF_USERNAME and STAFF_PASSWORD are set in Streamlit app secrets.")
        return
    with st.form("staff_login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        ok = st.form_submit_button("Log in", type="primary")
    if ok:
        if secrets.compare_digest(username, str(configured_user)) and secrets.compare_digest(password, str(configured_password)):
            st.session_state["staff_user"] = username
            st.rerun()
        else:
            st.error("Incorrect username or password.")


def calendar_page():
    st.header("Venue availability calendar")
    venues, opts = venues_options()
    if not venues:
        st.warning("No venues have been configured.")
        return
    venue_names = [v["name"] for v in venues]
    chosen_name = st.selectbox("Choose venue", venue_names, key="calendar_venue")
    chosen = next(v for v in venues if v["name"] == chosen_name)
    month = st.date_input("Select a date in the month to view", value=date.today(), key="calendar_month")
    st.caption(f"{chosen['description']} · Capacity: {chosen['capacity']} · Starting price: {money(chosen['base_price'])}")

    import calendar
    cal = calendar.Calendar(firstweekday=6)
    weeks = cal.monthdayscalendar(month.year, month.month)
    data = rows("""SELECT event_date,slot,status FROM bookings WHERE venue_id=?
                   AND status IN ('pending','active') AND event_date LIKE ?""",
                (chosen["id"], f"{month.year}-{month.month:02d}-%"))
    booked = {}
    for r in data:
        booked.setdefault(int(r["event_date"][-2:]), []).append(r)

    st.markdown("""
    <div style="display:flex;gap:16px;flex-wrap:wrap;margin:8px 0 16px">
      <span><span style="display:inline-block;width:12px;height:12px;background:#239b56;border-radius:3px"></span> Reserved / request received</span>
      <span><span style="display:inline-block;width:12px;height:12px;background:#eef2f6;border:1px solid #cbd5e1;border-radius:3px"></span> No booking recorded</span>
    </div>
    """, unsafe_allow_html=True)
    headers = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    header_cols = st.columns(7)
    for col, name in zip(header_cols, headers):
        col.markdown(f"**{name}**")
    for week in weeks:
        cols = st.columns(7)
        for col, day_num in zip(cols, week):
            if day_num == 0:
                col.markdown("<div style='height:78px'></div>", unsafe_allow_html=True)
                continue
            records = booked.get(day_num, [])
            if records:
                slots = ", ".join(sorted(set(r["slot"] for r in records)))
                bg, fg, state = "#239b56", "#ffffff", "BOOKED"
            else:
                slots = "No booking"
                bg, fg, state = "#eef2f6", "#263238", "AVAILABLE"
            col.markdown(
                f"""<div style="background:{bg};color:{fg};border-radius:9px;padding:8px 6px;
                min-height:78px;text-align:center;margin-bottom:8px">
                <div style="font-size:20px;font-weight:700">{day_num}</div>
                <div style="font-size:10px;font-weight:700;letter-spacing:.4px">{state}</div>
                <div style="font-size:10px;overflow-wrap:anywhere">{slots}</div></div>""",
                unsafe_allow_html=True)
    st.caption("A date may still have an available slot even if another slot is reserved. The booking form checks the selected venue, date and time slot.")
    with st.expander("Additional services and prices"):
        for o in opts:
            st.write(f"**{o['name']}** — {money(o['price'])}: {o['description']}")

def customer_tracking():
    st.header("Track a booking")
    token = st.text_input("Enter your booking reference")
    if st.button("Find booking"):
        found = rows("SELECT id FROM bookings WHERE token=?", (token.strip(),))
        if found:
            st.session_state["track_id"] = found[0]["id"]
        else:
            st.error("No booking found for that reference.")
    bid = st.session_state.get("track_id")
    if bid:
        b = booking_detail(bid)
        if b:
            st.write(f"**Booking #{b['id']} — {b['venue']}**")
            st.write(f"Client: {b['client_name']} · Date: {b['event_date']} · Slot: {b['slot']}")
            st.write(f"Status: **{b['status'].title()}** · Total: **{money(b['total_amount'])}**")
            pays = rows("SELECT * FROM payments WHERE booking_id=? AND status!='rejected' ORDER BY id", (bid,))
            paid = sum(float(p["amount"]) for p in pays if p["status"] == "confirmed")
            held = sum(float(p["amount"]) for p in pays)
            st.write(f"Confirmed paid: {money(paid)} · Payment requests awaiting confirmation: {money(held-paid)}")
            st.info("Payment gateway checkout is not connected. Customers can submit a payment reference after paying through the organisation's approved bank, card terminal or UPI channel; staff must verify it.")
            for detail in PAY_DETAILS: st.write(f"- {detail}")
            with st.form("customer_payment"):
                amount = st.number_input("Payment amount", min_value=0.0, max_value=max(0.0,float(b["total_amount"])-held), value=0.0)
                method = st.selectbox("Payment method", METHODS)
                reference = st.text_input("UPI / bank transaction reference")
                submit = st.form_submit_button("Submit payment details")
            if submit:
                if b["status"] == "cancelled": st.error("This booking is cancelled.")
                elif amount <= 0 or not reference.strip(): st.error("Enter a valid amount and transaction reference.")
                else:
                    execute("""INSERT INTO payments(booking_id,amount,paid_on,method,note,recorded_by,status,reference)
                               VALUES(?,?,?,?,?,'customer','pending',?)""",
                            (bid, amount, date.today().isoformat(), method, "Paid by customer", reference.strip()))
                    st.success("Payment details sent to staff for confirmation.")

def staff_bookings():
    st.header("Booking management")
    status_filter = st.selectbox("Filter bookings", ["All","Pending","Active","Cancelled"])
    sql = """SELECT b.*,v.name AS venue,
             COALESCE((SELECT SUM(amount) FROM payments WHERE booking_id=b.id AND status='confirmed'),0) AS paid
             FROM bookings b JOIN venues v ON v.id=b.venue_id ORDER BY b.event_date DESC"""
    data = rows(sql)
    if status_filter != "All":
        data = [b for b in data if b["status"] == status_filter.lower()]
    if not data:
        st.info("No bookings found.")
    for b in data:
        with st.expander(f"#{b['id']} · {b['client_name']} · {b['venue']} · {b['event_date']} · {b['status'].upper()}"):
            st.write(f"Phone: {b['phone']} · Email: {b['email'] or '—'}")
            st.write(f"Slot: {b['slot']} · Guests: {b['guests']} · Total: {money(b['total_amount'])} · Paid: {money(b['paid'])}")
            st.write(f"Reference: `{b['token']}` · Source: {b['source']}")
            if b["notes"]: st.write(f"Notes: {b['notes']}")
            selected_options = rows("""SELECT o.name,o.price FROM booking_options bo
                                       JOIN options o ON o.id=bo.option_id WHERE bo.booking_id=?""", (b["id"],))
            if selected_options:
                st.write("Extra services: " + ", ".join(f"{o['name']} ({money(o['price'])})" for o in selected_options))
            if b["status"] == "pending":
                c1,c2 = st.columns(2)
                if c1.button("Approve", key=f"approve_{b['id']}"):
                    execute("UPDATE bookings SET status='active' WHERE id=? AND status='pending'", (b["id"],)); st.rerun()
                if c2.button("Decline", key=f"decline_{b['id']}"):
                    execute("UPDATE bookings SET status='cancelled' WHERE id=? AND status='pending'", (b["id"],)); st.rerun()
            pays = rows("SELECT * FROM payments WHERE booking_id=? ORDER BY id", (b["id"],))
            if pays:
                st.markdown("**Payments**")
                for p in pays:
                    st.write(f"Payment #{p['id']}: {money(p['amount'])} · {p['method']} · {p['status']} · Ref: {p['reference'] or '—'}")
                    if p["status"] == "pending":
                        a1,a2 = st.columns(2)
                        if a1.button("Confirm payment", key=f"payok_{p['id']}"):
                            execute("UPDATE payments SET status='confirmed' WHERE id=?", (p["id"],)); st.rerun()
                        if a2.button("Reject payment", key=f"payno_{p['id']}"):
                            execute("UPDATE payments SET status='rejected' WHERE id=?", (p["id"],)); st.rerun()
            with st.form(f"record_payment_{b['id']}"):
                st.markdown("**Record staff payment**")
                a,c,d = st.columns(3)
                amount = a.number_input("Amount", min_value=0.0, value=0.0, key=f"amt_{b['id']}")
                method = c.selectbox("Method", METHODS, key=f"method_{b['id']}")
                paid_on = d.date_input("Paid on", value=date.today(), key=f"date_{b['id']}")
                note = st.text_input("Note", key=f"note_{b['id']}")
                if st.form_submit_button("Add payment"):
                    if amount > 0:
                        execute("INSERT INTO payments(booking_id,amount,paid_on,method,note,recorded_by,status) VALUES(?,?,?,?,?,?, 'confirmed')",
                                (b["id"],amount,paid_on.isoformat(),method,note,st.session_state["staff_user"]))
                        st.rerun()
                    else: st.error("Enter an amount greater than zero.")
            if b["status"] != "cancelled":
                if st.button("Cancel booking", key=f"cancel_{b['id']}"):
                    execute("UPDATE bookings SET status='cancelled' WHERE id=?", (b["id"],)); st.rerun()

def staff_manage_options():
    st.header("Manage additional services")
    current = rows("SELECT * FROM options ORDER BY name")
    if current:
        for option in current:
            st.write(f"**{option['name']}** — {money(option['price'])} · {option['description']}")
    else:
        st.info("No additional services are configured.")
    st.subheader("Add a new service")
    with st.form("add_option_form"):
        name = st.text_input("Service name")
        price = st.number_input("Price", min_value=0.0, step=100.0)
        description = st.text_area("Description")
        add = st.form_submit_button("Add service")
    if add:
        if not name.strip():
            st.error("Enter a service name.")
        elif rows("SELECT id FROM options WHERE lower(name)=lower(?)", (name.strip(),)):
            st.error("A service with that name already exists.")
        else:
            execute("INSERT INTO options(name,price,description) VALUES(?,?,?)",
                    (name.strip(), float(price), description.strip()))
            st.success("Service added. It is now available on the customer booking form.")
            st.rerun()

def main():
    init_db()
    st.title("📅 Ashirvad Venue Booking")
    st.caption("Venue availability, booking requests and payment tracking")
    st.warning("DEMO MODE: Streamlit Community Cloud's local SQLite storage is not persistent. Connect a managed shared database before accepting real customer bookings or payments.")
    pages = ["Availability", "Book a venue", "Track booking", "Staff"]
    page = st.sidebar.radio("Navigation", pages)
    if page == "Availability":
        calendar_page()
    elif page == "Book a venue":
        st.header("Request a venue booking")
        show_booking_form(False)
    elif page == "Track booking":
        customer_tracking()
    elif page == "Staff":
        if not st.session_state.get("staff_user"):
            staff_login()
        else:
            st.sidebar.success(f"Signed in: {st.session_state['staff_user']}")
            if st.sidebar.button("Log out"):
                del st.session_state["staff_user"]
                st.rerun()
            staff_page = st.radio("Staff tools", ["Bookings", "Create walk-in booking", "Manage extra services"])
            if staff_page == "Bookings":
                staff_bookings()
            elif staff_page == "Create walk-in booking":
                st.header("Register a walk-in customer")
                st.caption("Staff can enter customer details and create a booking directly.")
                show_booking_form(True)
            else:
                staff_manage_options()

if __name__ == "__main__":
    main()
