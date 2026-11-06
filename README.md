# Venue Booking — updated Streamlit version

## Features
- Month-grid venue calendar: green dates indicate a pending or active reservation.
- Customer-side booking requests with venue, date, slot, guest count, notes and extra services.
- Booking reference for customer tracking.
- Customer payment-reference submission; staff verify payment manually.
- Staff login, booking approval/rejection/cancellation, payment records and walk-in booking entry.
- Staff can add extra services and prices; those services appear on the customer booking form.

## Run locally
```powershell
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

## Staff login configuration
Set environment variables before local launch:
```powershell
$env:STAFF_USERNAME="your_staff_username"
$env:STAFF_PASSWORD="a-long-unique-password"
python -m streamlit run streamlit_app.py
```
On Streamlit Community Cloud, configure these in App Settings > Secrets:
```toml
STAFF_USERNAME = "your_staff_username"
STAFF_PASSWORD = "a-long-unique-password"
```

## Deployment and production warning
Push `streamlit_app.py`, `requirements.txt`, `.gitignore`, and `README.md` to GitHub.
Deploy from https://share.streamlit.io/ with entrypoint `streamlit_app.py`.

This package is for demonstration and testing. It uses SQLite local storage. Streamlit Community Cloud local files are not a reliable persistent/shared database. Before real organisational use, connect a managed PostgreSQL database, use individual staff accounts and role-based access, configure backups, and use a verified payment gateway. Payment-reference submission in this app is manual; it does not charge or verify a bank/card payment automatically. Do not upload a populated database or real customer information to a public repository.
