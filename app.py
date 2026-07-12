--import csv
import html
import io
import json
import logging
import os
import re
import sqlite3
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import wraps
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import google.generativeai as genai
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


load_dotenv(BASE_DIR / ".env")

logger.info("Starting Fake News Detection application")

app = Flask(__name__)
NEWS_FEED_URLS = [
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "http://news.bbc.co.uk/rss/newsonline_world_edition/front_page/rss.xml",
]

# Get port from environment (Render provides this)
PORT = int(os.getenv("PORT", 5000))
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config["DATABASE"] = str(BASE_DIR / "database.db")
app.config["GEMINI_MODEL"] = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("Gemini API configured successfully")
else:
    logger.warning("GEMINI_API_KEY not found in environment")


def get_db():
    """Open a database connection for the current request."""
    if "db" not in g:
        logger.debug("Opening database connection")
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    """Close the database connection when the request ends."""
    db = g.pop("db", None)
    if db is not None:
        logger.debug("Closing database connection")
        db.close()


def init_db():
    """Create required tables if they do not already exist."""
    logger.info("Initializing database")
    db = sqlite3.connect(app.config["DATABASE"], timeout=10)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT ''
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            news_text TEXT NOT NULL,
            result TEXT NOT NULL,
            confidence INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """
    )

    user_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}
    if "is_admin" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    if "created_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        cursor.execute(
            """
            UPDATE users
            SET created_at = ?
            WHERE created_at = ''
            """,
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),),
        )

    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_username = (os.getenv("ADMIN_USERNAME") or "").strip().lower()

    if admin_email:
        cursor.execute(
            "UPDATE users SET is_admin = 1 WHERE lower(email) = ?",
            (admin_email,),
        )
    if admin_username:
        cursor.execute(
            "UPDATE users SET is_admin = 1 WHERE lower(username) = ?",
            (admin_username,),
        )

    admin_exists = cursor.execute(
        "SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1"
    ).fetchone()
    if not admin_exists:
        first_user = cursor.execute(
            "SELECT id FROM users ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if first_user:
            cursor.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (first_user["id"],),
            )

    db.commit()
    db.close()
    logger.info("Database initialized successfully")


def login_required(route_function):
    """Allow access only to logged-in users."""

    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        return route_function(*args, **kwargs)

    return wrapper


def admin_required(route_function):
    """Allow access only to admin users."""

    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login", next=request.path))
        if not g.user or not g.user["is_admin"]:
            flash("Admin access is required for that page.", "danger")
            return redirect(url_for("index"))
        return route_function(*args, **kwargs)

    return wrapper


@app.before_request
def load_logged_in_user():
    """Load the current user from the session before each request."""
    g.user = None
    user_id = session.get("user_id")

    if user_id:
        g.user = get_db().execute(
            "SELECT id, username, email, is_admin FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if g.user is None:
            session.clear()


def clean_news_text(text):
    """Normalize user input and remove extra whitespace."""
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned


def is_valid_email(email):
    """Basic email validation for beginner-friendly form checks."""
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def build_analysis_prompt(news_text):
    return f"""
Analyze the following news text and respond only in JSON:

{{
  "result": "REAL or FAKE or UNCERTAIN",
  "confidence": number,
  "reason": "short explanation",
  "warnings": ["warning1", "warning2"]
}}

Rules:
- Return valid JSON only.
- Keep confidence between 0 and 100.
- Use concise beginner-friendly language.
- If the text is too vague or cannot be judged reliably, use "UNCERTAIN".

News:
{news_text}
""".strip()


def extract_json(text):
    """Safely extract JSON from a model response."""
    text = (text or "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```json\s*|^```\s*|```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def normalize_analysis(data):
    """Validate and normalize the Gemini JSON result."""
    result = str(data.get("result", "UNCERTAIN")).upper().strip()
    if result not in {"REAL", "FAKE", "UNCERTAIN"}:
        result = "UNCERTAIN"

    try:
        confidence = int(float(data.get("confidence", 50)))
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))

    reason = str(data.get("reason", "The system could not provide a clear explanation.")).strip()
    if not reason:
        reason = "The system could not provide a clear explanation."

    warnings = data.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    warnings = [str(item).strip() for item in warnings if str(item).strip()]

    return {
        "result": result,
        "confidence": confidence,
        "reason": reason,
        "warnings": warnings,
    }


def analyze_with_gemini(news_text):
    """Send the text to Gemini and return normalized analysis data."""
    logger.debug("Calling Gemini API for analysis")
    if not GEMINI_API_KEY:
        logger.error("Missing Gemini API key")
        raise RuntimeError("Gemini API key is missing. Add GEMINI_API_KEY to your .env file.")

    prompt = build_analysis_prompt(news_text)
    model = genai.GenerativeModel(app.config["GEMINI_MODEL"])

    try:
        logger.debug("Generating content with Gemini")
        response = model.generate_content(prompt)
        raw_text = getattr(response, "text", "") or ""
        logger.debug(f"Raw response: {raw_text[:100]}...")
        parsed = extract_json(raw_text)
        return normalize_analysis(parsed)
    except json.JSONDecodeError as error:
        logger.error(f"JSON decode error: {error}")
        raise ValueError("Gemini returned an invalid JSON response.") from error
    except Exception as error:
        logger.error(f"Gemini API error: {error}")
        raise RuntimeError(f"Could not analyze the news text: {error}") from error


def save_history(user_id, news_text, analysis):
    """Store an analysis result for a logged-in user."""
    logger.debug(f"Saving history for user {user_id}")
    try:
        get_db().execute(
            """
            INSERT INTO history (user_id, news_text, result, confidence, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                news_text,
                analysis["result"],
                analysis["confidence"],
                analysis["reason"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        get_db().commit()
        logger.info(f"History saved for user {user_id}")
        return True
    except sqlite3.DatabaseError as e:
        logger.error(f"Failed to save history: {e}")
        return False


def get_result_label(result):
    labels = {
        "REAL": "Likely Real",
        "FAKE": "Likely Fake",
        "UNCERTAIN": "Uncertain",
    }
    return labels.get(result, "Uncertain")


def fetch_todays_news(limit=6):
    """Fetch current headlines and prefer items published today."""
    today = datetime.now().date()
    headlines = []

    for feed_url in NEWS_FEED_URLS:
        try:
            request_headers = {"User-Agent": "FakeNewsDetection/1.0"}
            with urlopen(Request(feed_url, headers=request_headers), timeout=8) as response:
                root = ElementTree.fromstring(response.read())
        except (URLError, TimeoutError, ElementTree.ParseError) as error:
            logger.warning(f"News feed failed for {feed_url}: {error}")
            continue

        for item in root.findall(".//item"):
            title = html.unescape((item.findtext("title") or "").strip())
            link = (item.findtext("link") or "").strip()
            pub_date_raw = (item.findtext("pubDate") or "").strip()

            if not title or not link:
                continue

            published_today = False
            published_label = pub_date_raw
            if pub_date_raw:
                try:
                    parsed_date = parsedate_to_datetime(pub_date_raw)
                    published_today = parsed_date.date() == today
                    published_label = parsed_date.strftime("%d %b %Y, %I:%M %p")
                except (TypeError, ValueError, IndexError):
                    published_label = pub_date_raw

            headlines.append(
                {
                    "title": title,
                    "link": link,
                    "published_at": published_label,
                    "published_today": published_today,
                }
            )

        if headlines:
            break

    todays_items = [item for item in headlines if item["published_today"]]
    selected_items = todays_items[:limit] if todays_items else headlines[:limit]

    return {
        "date_label": datetime.now().strftime("%B %d, %Y"),
        "items": selected_items,
        "is_fallback": bool(selected_items) and not todays_items,
    }


def get_user_dashboard_data(user_id):
    """Build lightweight dashboard metrics for the signed-in user."""
    db = get_db()
    stats_row = db.execute(
        """
        SELECT
            COUNT(*) AS total_checks,
            SUM(CASE WHEN result = 'REAL' THEN 1 ELSE 0 END) AS real_count,
            SUM(CASE WHEN result = 'FAKE' THEN 1 ELSE 0 END) AS fake_count,
            SUM(CASE WHEN result = 'UNCERTAIN' THEN 1 ELSE 0 END) AS uncertain_count
        FROM history
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    recent_items = db.execute(
        """
        SELECT news_text, result, confidence, created_at
        FROM history
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 3
        """,
        (user_id,),
    ).fetchall()

    return {
        "total_checks": stats_row["total_checks"] or 0,
        "real_count": stats_row["real_count"] or 0,
        "fake_count": stats_row["fake_count"] or 0,
        "uncertain_count": stats_row["uncertain_count"] or 0,
        "recent_items": recent_items,
    }


def get_admin_dashboard_data():
    """Build high-level analytics for the admin workspace."""
    db = get_db()
    today_prefix = datetime.now().strftime("%Y-%m-%d")

    overview = db.execute(
        """
        SELECT
            COUNT(*) AS total_users,
            SUM(CASE WHEN is_admin = 1 THEN 1 ELSE 0 END) AS admin_count
        FROM users
        """
    ).fetchone()

    analysis_overview = db.execute(
        """
        SELECT
            COUNT(*) AS total_checks,
            SUM(CASE WHEN result = 'REAL' THEN 1 ELSE 0 END) AS real_count,
            SUM(CASE WHEN result = 'FAKE' THEN 1 ELSE 0 END) AS fake_count,
            SUM(CASE WHEN result = 'UNCERTAIN' THEN 1 ELSE 0 END) AS uncertain_count,
            SUM(CASE WHEN created_at LIKE ? THEN 1 ELSE 0 END) AS todays_checks
        FROM history
        """,
        (f"{today_prefix}%",),
    ).fetchone()

    user_rows = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.email,
            u.is_admin,
            u.created_at,
            COUNT(h.id) AS total_checks,
            MAX(h.created_at) AS last_activity
        FROM users u
        LEFT JOIN history h ON h.user_id = u.id
        GROUP BY u.id, u.username, u.email, u.is_admin, u.created_at
        ORDER BY total_checks DESC, u.id ASC
        """
    ).fetchall()

    recent_activity = db.execute(
        """
        SELECT
            h.id,
            h.news_text,
            h.result,
            h.confidence,
            h.created_at,
            u.username,
            u.email
        FROM history h
        JOIN users u ON u.id = h.user_id
        ORDER BY h.id DESC
        LIMIT 8
        """
    ).fetchall()

    return {
        "total_users": overview["total_users"] or 0,
        "admin_count": overview["admin_count"] or 0,
        "total_checks": analysis_overview["total_checks"] or 0,
        "real_count": analysis_overview["real_count"] or 0,
        "fake_count": analysis_overview["fake_count"] or 0,
        "uncertain_count": analysis_overview["uncertain_count"] or 0,
        "todays_checks": analysis_overview["todays_checks"] or 0,
        "user_rows": user_rows,
        "recent_activity": recent_activity,
    }


@app.route("/")
def index():
    if not g.user:
        return redirect(url_for("login"))

    return render_template(
        "index.html",
        dashboard_data=get_user_dashboard_data(g.user["id"]),
    )


@app.route("/analyze", methods=["POST"])
@login_required
def analyze():
    logger.info("Received analyze request")
    news_text = clean_news_text(request.form.get("news_text"))

    if len(news_text) < 20:
        logger.warning("Analyze request with insufficient text length")
        flash("Please enter at least 20 characters so the system has enough text to analyze.", "warning")
        return redirect(url_for("index"))

    try:
        logger.debug(f"Analyzing text: {news_text[:50]}...")
        analysis = analyze_with_gemini(news_text)
        logger.info(f"Analysis complete: {analysis['result']} ({analysis['confidence']}% confidence)")
    except (RuntimeError, ValueError) as error:
        logger.error(f"Analysis failed: {error}")
        flash(str(error), "danger")
        return redirect(url_for("index"))

    session["last_result"] = {
        "news_text": news_text,
        "result": analysis["result"],
        "confidence": analysis["confidence"],
        "reason": analysis["reason"],
        "warnings": analysis["warnings"],
    }

    if session.get("user_id"):
        saved = save_history(session["user_id"], news_text, analysis)
        if not saved:
            flash("Analysis completed, but saving to history failed. Please try logging in again.", "warning")

    return redirect(url_for("result"))


@app.route("/result")
@login_required
def result():
    result_data = session.get("last_result")
    if not result_data:
        flash("Analyze a news article first to see the result.", "warning")
        return redirect(url_for("index"))

    return render_template(
        "result.html",
        result_data=result_data,
        result_label=get_result_label(result_data["result"]),
    )


@app.route("/todays-news")
@login_required
def todays_news():
    news_payload = fetch_todays_news()

    if not news_payload["items"]:
        return jsonify(
            {
                "date_label": news_payload["date_label"],
                "items": [],
                "message": "Today's headlines are not available right now. Please try again in a moment.",
            }
        )

    message = f"Top headlines for {news_payload['date_label']}."
    if news_payload["is_fallback"]:
        message = f"Showing the latest available headlines near {news_payload['date_label']}."

    return jsonify(
        {
            "date_label": news_payload["date_label"],
            "items": news_payload["items"],
            "message": message,
        }
    )


@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template(
        "admin.html",
        admin_data=get_admin_dashboard_data(),
    )


@app.route("/admin/export")
@admin_required
def admin_export():
    activity_items = get_db().execute(
        """
        SELECT
            u.username,
            u.email,
            h.news_text,
            h.result,
            h.confidence,
            h.reason,
            h.created_at
        FROM history h
        JOIN users u ON u.id = h.user_id
        ORDER BY h.id DESC
        """
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Username", "Email", "News Text", "Result", "Confidence", "Reason", "Created At"])

    for item in activity_items:
        writer.writerow(
            [
                item["username"],
                item["email"],
                item["news_text"],
                get_result_label(item["result"]),
                item["confidence"],
                item["reason"],
                item["created_at"],
            ]
        )

    memory_file = io.BytesIO()
    memory_file.write(output.getvalue().encode("utf-8-sig"))
    memory_file.seek(0)

    return send_file(
        memory_file,
        as_attachment=True,
        download_name="admin_analysis_report.csv",
        mimetype="text/csv",
    )


@app.route("/admin/users/<int:user_id>/toggle-role", methods=["POST"])
@admin_required
def toggle_admin_role(user_id):
    if g.user["id"] == user_id:
        flash("You cannot change your own admin role from this panel.", "warning")
        return redirect(url_for("admin_dashboard"))

    user = get_db().execute(
        "SELECT id, username, is_admin FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user:
        flash("Selected user was not found.", "danger")
        return redirect(url_for("admin_dashboard"))

    new_value = 0 if user["is_admin"] else 1
    get_db().execute(
        "UPDATE users SET is_admin = ? WHERE id = ?",
        (new_value, user_id),
    )
    get_db().commit()
    flash(
        f"{user['username']} is now {'an admin' if new_value else 'a regular user'}.",
        "success",
    )
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<int:user_id>/clear-history", methods=["POST"])
@admin_required
def admin_clear_user_history(user_id):
    if g.user["id"] == user_id:
        flash("Use your personal history page if you want to clear your own records.", "warning")
        return redirect(url_for("admin_dashboard"))

    user = get_db().execute(
        "SELECT id, username FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user:
        flash("Selected user was not found.", "danger")
        return redirect(url_for("admin_dashboard"))

    get_db().execute("DELETE FROM history WHERE user_id = ?", (user_id,))
    get_db().commit()
    flash(f"History cleared for {user['username']}.", "info")
    return redirect(url_for("admin_dashboard"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please fill in all signup fields.", "warning")
            return render_template("signup.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "warning")
            return render_template("signup.html")

        if not is_valid_email(email):
            flash("Please enter a valid email address.", "warning")
            return render_template("signup.html")

        db = get_db()
        existing_user = db.execute(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (username, email),
        ).fetchone()

        if existing_user:
            logger.warning(f"Signup failed - user exists: {username}")
            flash("Username or email already exists. Please use a different one.", "danger")
            return render_template("signup.html")

        try:
            db.execute(
                """
                INSERT INTO users (username, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    generate_password_hash(password),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            db.commit()
            logger.info(f"New user registered: {username}")
        except sqlite3.IntegrityError:
            logger.warning(f"Signup failed - integrity error: {username}")
            flash("Username or email already exists. Please use a different one.", "danger")
            return render_template("signup.html")

        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))

    if request.method == "POST":
        username_or_email = request.form.get("username_or_email", "").strip()
        password = request.form.get("password", "")
        next_page = request.args.get("next")

        if not username_or_email or not password:
            flash("Please enter both login fields.", "warning")
            return render_template("login.html")

        user = get_db().execute(
            """
            SELECT * FROM users
            WHERE username = ? OR email = ?
            """,
            (username_or_email, username_or_email.lower()),
        ).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            logger.warning(f"Login failed for: {username_or_email}")
            flash("Invalid username/email or password.", "danger")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user["id"]
        logger.info(f"User logged in: {user['username']}")
        flash("Login successful.", "success")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    user_id = session.get("user_id")
    session.clear()
    if user_id:
        logger.info(f"User logged out: {user_id}")
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/history")
@login_required
def history():
    logger.debug("Loading history page")
    history_items = get_db().execute(
        """
        SELECT id, news_text, result, confidence, reason, created_at
        FROM history
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],),
    ).fetchall()
    logger.info(f"Loaded {len(history_items)} history items for user {session['user_id']}")
    return render_template("history.html", history_items=history_items)


@app.route("/history/export")
@login_required
def export_history():
    history_items = get_db().execute(
        """
        SELECT news_text, result, confidence, reason, created_at
        FROM history
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (session["user_id"],),
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["News Text", "Result", "Confidence", "Reason", "Created At"])

    for item in history_items:
        writer.writerow(
            [
                item["news_text"],
                get_result_label(item["result"]),
                item["confidence"],
                item["reason"],
                item["created_at"],
            ]
        )

    memory_file = io.BytesIO()
    memory_file.write(output.getvalue().encode("utf-8-sig"))
    memory_file.seek(0)

    return send_file(
        memory_file,
        as_attachment=True,
        download_name="analysis_history.csv",
        mimetype="text/csv",
    )


@app.route("/history/clear", methods=["POST"])
@login_required
def clear_history():
    logger.info(f"Clearing history for user {session['user_id']}")
    get_db().execute("DELETE FROM history WHERE user_id = ?", (session["user_id"],))
    get_db().commit()
    flash("Your history has been cleared.", "info")
    return redirect(url_for("history"))


@app.route("/about")
def about():
    return render_template("about.html")


with app.app_context():
    try:
        init_db()
    except sqlite3.DatabaseError as error:
        logger.error(f"Database initialization failed during startup: {error}")


# Run the app - required for local development, gunicorn handles it in production
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
