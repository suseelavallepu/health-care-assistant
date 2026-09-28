# Healthcare Assistant Flask

## Windows CMD
1. Open CMD.
2. `cd path\to\healthcare-assistant`
3. `python -m venv venv`
4. `venv\Scripts\activate`
5. `python -m pip install -r requirements.txt`
6. Copy `.env.example` to `.env` and set SECRET_KEY, GEMINI_API_KEY, SMTP settings, ADMIN_EMAIL and ADMIN_PASSWORD.
7. `python app.py`
8. Open `http://127.0.0.1:5000`

No Node.js/npm is required.

The SQLite database is created automatically in `instance/healthcare.db` and useful reference symptoms, conditions, mappings and medicine information are seeded. No fake user health values are seeded.

Gemini is called only by the Flask backend. SMTP is used for user/admin password reset. ReportLab creates the personal health PDF from database data.

For Gmail SMTP, use an App Password where required. For production, disable debug mode, use HTTPS, a strong secret and a production WSGI server.

This is a general health information application, not a diagnostic or prescribing system.
