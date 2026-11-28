# ==============================================================================
# SECTION 1: IMPORTS & APP CONFIGURATION
# ==============================================================================
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
import os
import json
import re
import socket
import sqlite3
import uuid
import glob
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "jhand-garan-super-league-session-4-secret-key"

TOURNAMENT_TITLE = "JHAND GARAN SUPER LEAGE 2026 SESION 4"
FOOTER_TOURNAMENT_TITLE = "SUPER LEAGE 2026 SESION 4"
FOOTER_CREDIT = "DEVELOP BY RAJA FARAZ TUR 92-3013660354"
MAX_TEAMS = 16
SQUAD_MEMBER_COUNT = 15
VALID_STATUSES = {"REGISRD", "CXL", "WAIT"}

# Admin Credentials
ADMIN_ID = "admin"
ADMIN_PASS = "turk2026"

# Optional background video (.mp4 URL or YouTube URL, or place static/videos/cricket-bg.mp4)
BG_VIDEO_URL = ""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "tournament.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
VIDEO_FOLDER = os.path.join(BASE_DIR, "static", "videos")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(VIDEO_FOLDER, exist_ok=True)


# ==============================================================================
# SECTION 2: HELPER FUNCTIONS (PHONE NORMALIZATION, MEDIA & NETWORK)
# ==============================================================================
def normalize_phone(raw_phone):
    digits = re.sub(r"\D", "", raw_phone or "")
    if digits.startswith("92") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def has_local_bg_video():
    video_file = os.path.join(VIDEO_FOLDER, "cricket-bg.mp4")
    return os.path.isfile(video_file) and os.path.getsize(video_file) > 0


def extract_youtube_id(url_str):
    if not url_str:
        return ""
    patterns = [
        r"(?:v=|\/)([0-9A-Za-z_-]{11})(?:[&?\/]|$)",
        r"youtu\.be\/([0-9A-Za-z_-]{11})(?:[&?\/]|$)",
        r"embed\/([0-9A-Za-z_-]{11})(?:[&?\/]|$)",
    ]
    for pat in patterns:
        m = re.search(pat, url_str.strip())
        if m:
            return m.group(1)
    return ""


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_image(file_storage):
    if not file_storage or not file_storage.filename:
        return ""
    if not allowed_file(file_storage.filename):
        return ""
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}_{secure_filename(file_storage.filename)}"
    if not unique_name.lower().endswith(f".{ext}"):
        unique_name = f"{uuid.uuid4().hex}.{ext}"
    full_path = os.path.join(UPLOAD_FOLDER, unique_name)
    file_storage.save(full_path)
    return f"/static/uploads/{unique_name}"


# ==============================================================================
# SECTION 3: DATABASE INITIALIZATION & DEFAULT GROUPS
# ==============================================================================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT NOT NULL,
            captain_name TEXT NOT NULL,
            captain_image TEXT DEFAULT '',
            phone TEXT NOT NULL,
            city TEXT NOT NULL,
            squad_json TEXT NOT NULL,
            status TEXT DEFAULT 'WAIT',
            group_id INTEGER DEFAULT NULL
        )
        """
    )

    c.execute("PRAGMA table_info(teams)")
    cols = [col[1] for col in c.fetchall()]
    if "status" not in cols:
        c.execute("ALTER TABLE teams ADD COLUMN status TEXT DEFAULT 'WAIT'")
    if "group_id" not in cols:
        c.execute("ALTER TABLE teams ADD COLUMN group_id INTEGER DEFAULT NULL")

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team1_id INTEGER NOT NULL,
            team2_id INTEGER NOT NULL,
            match_date TEXT NOT NULL,
            match_time TEXT NOT NULL
        )
        """
    )

    for default_group in ("GROUP A", "GROUP B"):
        c.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (default_group,))

    conn.commit()
    conn.close()


def is_duplicate_active_phone(cursor, phone_input, exclude_team_id=None):
    target_norm = normalize_phone(phone_input)
    if not target_norm:
        return False
    if exclude_team_id is not None:
        cursor.execute(
            "SELECT phone FROM teams WHERE COALESCE(status, 'WAIT') != 'CXL' AND id != ?",
            (exclude_team_id,),
        )
    else:
        cursor.execute("SELECT phone FROM teams WHERE COALESCE(status, 'WAIT') != 'CXL'")
    for (existing_phone,) in cursor.fetchall():
        if normalize_phone(existing_phone) == target_norm:
            return True
    return False


def get_first_group_id(cursor):
    cursor.execute("SELECT id FROM groups ORDER BY id ASC LIMIT 1")
    row = cursor.fetchone()
    return row[0] if row else None


# ==============================================================================
# SECTION 4: ROSTER & PORTAL PAYLOAD BUILDERS
# ==============================================================================
def build_full_roster(team_name, captain_name, captain_image, parsed_squad):
    by_slot = {}
    for idx, item in enumerate(parsed_squad or [], start=1):
        slot_num = item.get("slot") if isinstance(item.get("slot"), int) else idx
        by_slot[slot_num] = item

    cards = [
        {
            "team_name": team_name or "TEAM",
            "name": captain_name or "CAPTAIN",
            "role": "CAPTAIN",
            "image": captain_image or "",
        }
    ]

    for i in range(1, SQUAD_MEMBER_COUNT + 1):
        entry = by_slot.get(i, {})
        p_name = (entry.get("name") or "").strip()
        p_role = (entry.get("role") or "All Rounder").strip()
        if p_role not in {"Batsman", "Bowler", "All Rounder"}:
            p_role = "All Rounder"
        p_img = (entry.get("image") or "").strip()

        cards.append(
            {
                "team_name": team_name or "TEAM",
                "name": p_name if p_name else f"PLAYER #{i}",
                "role": p_role.upper(),
                "image": p_img,
            }
        )

    return cards


def fetch_portal_payload():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT id, name FROM groups ORDER BY id ASC")
    group_rows = c.fetchall()

    c.execute(
        """
        SELECT id, team_name, captain_name, captain_image, phone, city, squad_json,
               COALESCE(status, 'WAIT'), group_id
        FROM teams
        ORDER BY id DESC
        """
    )
    team_rows = c.fetchall()

    c.execute(
        """
        SELECT id, team1_id, team2_id, match_date, match_time
        FROM matches
        ORDER BY id ASC
        """
    )
    match_rows = c.fetchall()
    conn.close()

    group_name_map = {g[0]: g[1] for g in group_rows}
    first_gid = group_rows[0][0] if group_rows else None

    teams = []
    team_by_id = {}
    registered_count = 0

    for row in team_rows:
        try:
            parsed_squad = json.loads(row[6]) if row[6] else []
        except Exception:
            parsed_squad = []

        status_val = row[7] if row[7] in VALID_STATUSES else "WAIT"
        if status_val == "REGISRD":
            registered_count += 1

        gid = row[8]
        if gid is None and status_val == "REGISRD":
            gid = first_gid
        if status_val == "CXL":
            gid = None

        team_obj = {
            "id": row[0],
            "team_name": row[1],
            "captain_name": row[2],
            "captain_image": row[3],
            "phone": row[4],
            "city": row[5],
            "squad_raw": parsed_squad,
            "roster_cards": build_full_roster(row[1], row[2], row[3], parsed_squad),
            "status": status_val,
            "group_id": gid,
            "group_name": group_name_map.get(gid, ""),
        }
        teams.append(team_obj)
        team_by_id[row[0]] = team_obj

    groups_data = []
    for gid, gname in group_rows:
        g_teams = [
            t for t in teams
            if t["status"] != "CXL" and t["group_id"] == gid
        ]
        groups_data.append(
            {
                "id": gid,
                "name": gname,
                "teams": g_teams,
            }
        )

    matches_data = []
    for m_id, t1_id, t2_id, m_date, m_time in match_rows:
        t1 = team_by_id.get(t1_id)
        t2 = team_by_id.get(t2_id)
        if not t1 or not t2:
            continue
        matches_data.append(
            {
                "id": m_id,
                "team1_id": t1["id"],
                "team1_name": t1["team_name"],
                "team1_captain": t1["captain_name"],
                "team1_image": t1["captain_image"],
                "team2_id": t2["id"],
                "team2_name": t2["team_name"],
                "team2_captain": t2["captain_name"],
                "team2_image": t2["captain_image"],
                "match_date": m_date,
                "match_time": m_time,
            }
        )

    return {
        "teams": teams,
        "groups": groups_data,
        "matches": matches_data,
        "total": registered_count,
        "max_teams": MAX_TEAMS,
    }


# ==============================================================================
# SECTION 5: ROUTES (LIVE API, REGISTRATION, EDIT, STATUS, GROUPS & MATCHES)
# ==============================================================================
@app.route("/api/live-teams")
def api_live_teams():
    return jsonify(fetch_portal_payload())


@app.route("/admin/login", methods=["POST"])
def admin_login():
    entered_id = request.form.get("admin_id", "").strip()
    entered_pass = request.form.get("admin_pass", "").strip()
    if entered_id == ADMIN_ID and entered_pass == ADMIN_PASS:
        session["is_admin"] = True
    return redirect(url_for("home"))


@app.route("/developer-photo")
def developer_photo():
    base_dir = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.join(base_dir, "static", "images", "developer.png"),
        os.path.join(base_dir, "static", "images", "developer.jpg"),
        os.path.join(base_dir, "static", "images", "developer.jpeg"),
        os.path.join(base_dir, "static", "images", "developer.webp"),
        os.path.join(base_dir, "static", "uploads", "developer.png"),
        os.path.join(base_dir, "static", "uploads", "2b167ed22f8e4bc48f0407fbb2d2dbb2_FARZAZ.PNG"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return send_file(path)

    fallback_patterns = [
        os.path.join(base_dir, "static", "images", "*"),
        os.path.join(base_dir, "static", "uploads", "*FARZAZ*"),
        os.path.join(base_dir, "static", "uploads", "*"),
    ]
    for pat in fallback_patterns:
        for f in sorted(glob.glob(pat)):
            if os.path.isfile(f) and f.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                return send_file(f)

    return ("Developer photo not found", 404)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("home"))


@app.route("/admin/team/<int:team_id>/edit", methods=["POST"])
def edit_team(team_id):
    if not session.get("is_admin"):
        return redirect(url_for("home"))

    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT team_name, captain_name, captain_image, phone, city, squad_json FROM teams WHERE id = ?",
        (team_id,),
    )
    row = c.fetchone()
    if not row:
        conn.close()
        return redirect(url_for("home"))

    old_team_name, old_captain_name, old_captain_img, old_phone, old_city, old_squad_json = row
    try:
        existing_squad = json.loads(old_squad_json) if old_squad_json else []
    except Exception:
        existing_squad = []

    by_slot = {}
    for idx, item in enumerate(existing_squad, start=1):
        slot_num = item.get("slot") if isinstance(item.get("slot"), int) else idx
        by_slot[slot_num] = item

    new_team_name = request.form.get("team_name", "").strip() or old_team_name
    new_captain_name = request.form.get("captain_name", "").strip() or old_captain_name
    new_phone = request.form.get("phone", "").strip() or old_phone
    new_city = request.form.get("city", "").strip() or old_city

    uploaded_cap_img = save_uploaded_image(request.files.get("captain_image"))
    new_captain_img = uploaded_cap_img if uploaded_cap_img else old_captain_img

    updated_squad = []
    for i in range(1, SQUAD_MEMBER_COUNT + 1):
        prev = by_slot.get(i, {})
        m_name = request.form.get(f"edit_player_name_{i}", "").strip()
        m_role = request.form.get(f"edit_player_role_{i}", prev.get("role") or "All Rounder").strip()
        if m_role not in {"Batsman", "Bowler", "All Rounder"}:
            m_role = "All Rounder"

        uploaded_m_img = save_uploaded_image(request.files.get(f"edit_player_image_{i}"))
        m_img = uploaded_m_img if uploaded_m_img else (prev.get("image") or "")

        updated_squad.append(
            {
                "slot": i,
                "name": m_name,
                "role": m_role,
                "image": m_img,
            }
        )

    c.execute(
        """
        UPDATE teams
        SET team_name = ?, captain_name = ?, captain_image = ?, phone = ?, city = ?, squad_json = ?
        WHERE id = ?
        """,
        (
            new_team_name,
            new_captain_name,
            new_captain_img,
            new_phone,
            new_city,
            json.dumps(updated_squad),
            team_id,
        ),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("home"))


@app.route("/admin/team/<int:team_id>/status", methods=["POST"])
def update_team_status(team_id):
    if not session.get("is_admin"):
        return redirect(url_for("home"))

    new_status = request.form.get("status", "WAIT").strip().upper()
    if new_status not in VALID_STATUSES:
        new_status = "WAIT"

    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if new_status == "REGISRD":
        c.execute("SELECT group_id FROM teams WHERE id = ?", (team_id,))
        row = c.fetchone()
        target_gid = row[0] if (row and row[0] is not None) else get_first_group_id(c)
        c.execute(
            "UPDATE teams SET status = 'REGISRD', group_id = ? WHERE id = ?",
            (target_gid, team_id),
        )
    elif new_status == "CXL":
        c.execute(
            "UPDATE teams SET status = 'CXL', group_id = NULL WHERE id = ?",
            (team_id,),
        )
    else:
        c.execute(
            "UPDATE teams SET status = 'WAIT' WHERE id = ?",
            (team_id,),
        )

    conn.commit()
    conn.close()
    return redirect(url_for("home"))


@app.route("/admin/group/add", methods=["POST"])
def add_group():
    if not session.get("is_admin"):
        return redirect(url_for("home"))

    raw_name = request.form.get("group_name", "").strip().upper()
    if raw_name:
        group_label = raw_name if raw_name.startswith("GROUP ") else f"GROUP {raw_name}"
        init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO groups (name) VALUES (?)", (group_label,))
        conn.commit()
        conn.close()
    return redirect(url_for("home"))


@app.route("/admin/group/<int:group_id>/add-team", methods=["POST"])
def add_team_to_group(group_id):
    if not session.get("is_admin"):
        return redirect(url_for("home"))

    team_id_raw = request.form.get("team_id", "").strip()
    if team_id_raw.isdigit():
        team_id = int(team_id_raw)
        init_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM groups WHERE id = ?", (group_id,))
        if c.fetchone():
            c.execute("SELECT COALESCE(status, 'WAIT') FROM teams WHERE id = ?", (team_id,))
            t_row = c.fetchone()
            if t_row:
                next_status = "REGISRD" if t_row[0] == "CXL" else t_row[0]
                c.execute(
                    "UPDATE teams SET group_id = ?, status = ? WHERE id = ?",
                    (group_id, next_status, team_id),
                )
                conn.commit()
        conn.close()
    return redirect(url_for("home"))


@app.route("/admin/group/remove-team/<int:team_id>", methods=["POST"])
def remove_team_from_group(team_id):
    if not session.get("is_admin"):
        return redirect(url_for("home"))

    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE teams SET group_id = NULL WHERE id = ?", (team_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))


@app.route("/admin/match/add", methods=["POST"])
def add_match():
    if not session.get("is_admin"):
        return redirect(url_for("home"))

    t1_raw = request.form.get("team1_id", "").strip()
    t2_raw = request.form.get("team2_id", "").strip()
    m_date = request.form.get("match_date", "").strip()
    m_time = request.form.get("match_time", "").strip()

    if t1_raw.isdigit() and t2_raw.isdigit() and m_date and m_time:
        t1_id = int(t1_raw)
        t2_id = int(t2_raw)
        if t1_id != t2_id:
            init_db()
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "INSERT INTO matches (team1_id, team2_id, match_date, match_time) VALUES (?, ?, ?, ?)",
                (t1_id, t2_id, m_date, m_time),
            )
            conn.commit()
            conn.close()
    return redirect(url_for("home"))


@app.route("/admin/match/<int:match_id>/delete", methods=["POST"])
def delete_match(match_id):
    if not session.get("is_admin"):
        return redirect(url_for("home"))

    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM matches WHERE id = ?", (match_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("home"))


@app.route("/", methods=["GET", "POST"])
def home():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    error_message = ""
    open_reg_modal = False

    if request.method == "POST":
        team_name = request.form.get("team_name", "").strip()
        captain_name = request.form.get("captain_name", "").strip()
        phone = request.form.get("phone", "").strip()
        city = request.form.get("city", "").strip()

        c.execute("SELECT COUNT(*) FROM teams WHERE COALESCE(status, 'WAIT') = 'REGISRD'")
        reg_count = c.fetchone()[0]

        if not normalize_phone(phone):
            error_message = "Please enter a valid contact or mobile number."
            open_reg_modal = True
        elif is_duplicate_active_phone(c, phone):
            error_message = (
                "This mobile number is already registered with another team. "
                "Only one team can be registered per mobile number."
            )
            open_reg_modal = True
        elif reg_count < MAX_TEAMS and team_name and captain_name and phone and city:
            captain_img_path = save_uploaded_image(request.files.get("captain_image"))

            squad_members = []
            for i in range(1, SQUAD_MEMBER_COUNT + 1):
                member_name = request.form.get(f"player_name_{i}", "").strip()
                member_role = request.form.get(f"player_role_{i}", "All Rounder").strip()
                member_img_path = save_uploaded_image(request.files.get(f"player_image_{i}"))

                squad_members.append(
                    {
                        "slot": i,
                        "name": member_name,
                        "role": member_role if member_role in {"Batsman", "Bowler", "All Rounder"} else "All Rounder",
                        "image": member_img_path,
                    }
                )

            c.execute(
                """
                INSERT INTO teams (team_name, captain_name, captain_image, phone, city, squad_json, status, group_id)
                VALUES (?, ?, ?, ?, ?, ?, 'WAIT', NULL)
                """,
                (
                    team_name,
                    captain_name,
                    captain_img_path,
                    phone,
                    city,
                    json.dumps(squad_members),
                ),
            )
            conn.commit()
            conn.close()
            return redirect(url_for("home"))

    conn.close()
    payload = fetch_portal_payload()
    yt_id = extract_youtube_id(BG_VIDEO_URL)
    direct_mp4 = BG_VIDEO_URL if (BG_VIDEO_URL and not yt_id) else ""

    return render_template(
        "index.html",
        tournament_title=TOURNAMENT_TITLE,
        footer_tournament_title=FOOTER_TOURNAMENT_TITLE,
        footer_credit=FOOTER_CREDIT,
        has_bg_video=has_local_bg_video(),
        bg_youtube_id=yt_id,
        bg_direct_mp4=direct_mp4,
        teams=payload["teams"],
        groups=payload["groups"],
        matches=payload["matches"],
        total=payload["total"],
        max_teams=MAX_TEAMS,
        squad_count=SQUAD_MEMBER_COUNT,
        is_admin=bool(session.get("is_admin")),
        error_message=error_message,
        open_reg_modal=open_reg_modal,
    )


# ==============================================================================
# SECTION 6: APPLICATION ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    init_db()
    local_ip = get_local_ip()
    print(f"PC URL:     http://127.0.0.1:5000")
    print(f"Mobile URL: http://{local_ip}:5000 (Same Wi-Fi)")
    app.run(host="0.0.0.0", port=5000, debug=True)
