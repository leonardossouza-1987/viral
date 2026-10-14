import os, sqlite3, uuid
from datetime import datetime
from flask import Flask, render_template, request, session, jsonify
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
from admin_api import admin_api

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["300 per hour"],
    storage_uri="memory://",
)

Talisman(
    app,
    force_https=False,
    content_security_policy={
        "default-src": "'self'",
        "img-src": "'self' data: https://img.youtube.com https://i.ytimg.com https:",
        "script-src": "'self' 'unsafe-inline'",
        "style-src": "'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src": "'self' https://fonts.gstatic.com",
    },
    frame_options="DENY",
)

app.secret_key = "dev-sem-auth"
LIMITE_SINALIZACOES = 10

_db_iniciado = False

def garantir_db():
    global _db_iniciado
    if _db_iniciado:
        return
    try:
        init_db()
        _db_iniciado = True
    except Exception as e:
        print(f"[init_db erro] {e}")

def init_db():
    conn = sqlite3.connect("viral.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        anon_id TEXT, anon_name TEXT,
        content TEXT, link TEXT,
        link_title TEXT, link_description TEXT, link_image TEXT,
        created_at TEXT,
        frozen INTEGER DEFAULT 0,
        reports INTEGER DEFAULT 0)""")
    c.execute("CREATE TABLE IF NOT EXISTS likes (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, anon_id TEXT, UNIQUE(post_id, anon_id))")
    c.execute("CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, anon_id TEXT, anon_name TEXT, content TEXT, created_at TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS flags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER, anon_id TEXT, created_at TEXT,
        UNIQUE(post_id, anon_id))""")
    conn.commit(); conn.close()

def db():
    conn = sqlite3.connect("viral.db"); conn.row_factory = sqlite3.Row; return conn

def get_anon():
    if "anon_id" not in session:
        session["anon_id"] = str(uuid.uuid4())
        session["anon_name"] = "Anônimo #" + session["anon_id"][:4].upper()
    return session["anon_id"], session["anon_name"]

def fetch_link_preview(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
        r = requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        def meta(prop):
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
            return tag["content"].strip() if tag and tag.get("content") else None
        image = meta("og:image")
        if "youtube.com" in url or "youtu.be" in url:
            vid = None
            if "v=" in url: vid = url.split("v=")[1].split("&")[0]
            elif "youtu.be/" in url: vid = url.split("youtu.be/")[1].split("?")[0]
            if vid: image = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
        return {
            "title": meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else None),
            "description": meta("og:description") or meta("description"),
            "image": image,
        }
    except Exception:
        return {"title": None, "description": None, "image": None}

@app.route("/health")
def health():
    return "ok", 200

@app.route("/")
def index():
    garantir_db()
    get_anon()
    return render_template("feed.html", anon_name=session["anon_name"])

@app.route("/api/posts", methods=["GET"])
def api_posts():
    garantir_db()
    anon_id, _ = get_anon()
    conn = db(); c = conn.cursor()
    c.execute("""SELECT p.id, p.content, p.link, p.link_title, p.link_description, p.link_image,
        p.created_at, p.anon_name AS author, p.reports,
        (SELECT COUNT(*) FROM likes WHERE post_id = p.id) AS likes,
        (SELECT COUNT(*) FROM comments WHERE post_id = p.id) AS comments,
        (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND anon_id = ?) AS liked_by_me,
        (SELECT COUNT(*) FROM flags WHERE post_id = p.id AND anon_id = ?) AS flagged_by_me
        FROM posts p WHERE p.frozen = 0 ORDER BY p.created_at DESC""", (anon_id, anon_id))
    rows = [dict(r) for r in c.fetchall()]; conn.close()
    return jsonify(rows)

@app.route("/api/posts", methods=["POST"])
@limiter.limit("10 per minute")
def api_create():
    garantir_db()
    anon_id, anon_name = get_anon()
    d = request.get_json()
    content = (d.get("content") or "").strip()
    link = (d.get("link") or "").strip()
    if not content and not link: return jsonify({"error": "vazio"}), 400
    preview = fetch_link_preview(link) if link else {"title": None, "description": None, "image": None}
    conn = db(); c = conn.cursor()
    c.execute("""INSERT INTO posts (anon_id, anon_name, content, link, link_title, link_description, link_image, created_at, frozen, reports)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0)""",
              (anon_id, anon_name, content, link, preview["title"], preview["description"], preview["image"], datetime.utcnow().isoformat()))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@app.route("/api/like/<int:pid>", methods=["POST"])
@limiter.limit("30 per minute")
def api_like(pid):
    garantir_db()
    anon_id, _ = get_anon()
    conn = db(); c = conn.cursor()
    c.execute("SELECT id FROM likes WHERE post_id = ? AND anon_id = ?", (pid, anon_id))
    if c.fetchone():
        c.execute("DELETE FROM likes WHERE post_id = ? AND anon_id = ?", (pid, anon_id))
        liked = False
    else:
        c.execute("INSERT INTO likes (post_id, anon_id) VALUES (?, ?)", (pid, anon_id))
        liked = True
    conn.commit()
    c.execute("SELECT COUNT(*) FROM likes WHERE post_id = ?", (pid,))
    total = c.fetchone()[0]; conn.close()
    return jsonify({"liked": liked, "total": total})

@app.route("/api/flag/<int:pid>", methods=["POST"])
@limiter.limit("5 per minute")
def api_flag(pid):
    garantir_db()
    anon_id, _ = get_anon()
    conn = db(); c = conn.cursor()
    c.execute("SELECT id FROM flags WHERE post_id = ? AND anon_id = ?", (pid, anon_id))
    if c.fetchone():
        conn.close(); return jsonify({"ok": True, "ja_sinalizou": True})
    c.execute("INSERT INTO flags (post_id, anon_id, created_at) VALUES (?, ?, ?)",
              (pid, anon_id, datetime.utcnow().isoformat()))
    c.execute("UPDATE posts SET reports = reports + 1 WHERE id = ?", (pid,))
    c.execute("SELECT reports FROM posts WHERE id = ?", (pid,))
    row = c.fetchone()
    total = row["reports"] if row else 0
    congelado = False
    if total >= LIMITE_SINALIZACOES:
        c.execute("UPDATE posts SET frozen = 1 WHERE id = ?", (pid,))
        congelado = True
    conn.commit(); conn.close()
    return jsonify({"ok": True, "total": total, "congelado": congelado})

@app.route("/api/comments/<int:pid>", methods=["GET", "POST"])
def api_comments(pid):
    garantir_db()
    anon_id, anon_name = get_anon()
    conn = db(); c = conn.cursor()
    if request.method == "POST":
        d = request.get_json(); content = (d.get("content") or "").strip()
        if not content: return jsonify({"error": "vazio"}), 400
        c.execute("INSERT INTO comments (post_id, anon_id, anon_name, content, created_at) VALUES (?, ?, ?, ?, ?)",
                  (pid, anon_id, anon_name, content, datetime.utcnow().isoformat()))
        conn.commit()
    c.execute("SELECT content, created_at, anon_name AS author FROM comments WHERE post_id = ? ORDER BY created_at ASC", (pid,))
    rows = [dict(r) for r in c.fetchall()]; conn.close()
    return jsonify(rows)

app.register_blueprint(admin_api)


@app.route("/api/blocos", methods=["GET"])
def api_blocos():
    anon_id, _ = get_anon()
    conn = db(); c = conn.cursor()

    base_sql = """SELECT p.id, p.content, p.link, p.link_hash, p.link_title, p.link_description, p.link_image,
        p.tags, p.created_at, p.anon_name AS author, p.reports,
        (SELECT COUNT(*) FROM likes WHERE post_id = p.id) AS likes,
        (SELECT COUNT(*) FROM comments WHERE post_id = p.id) AS comments,
        (SELECT COUNT(*) FROM likes WHERE post_id = p.id AND anon_id = ?) AS liked_by_me,
        (SELECT COUNT(*) FROM flags WHERE post_id = p.id AND anon_id = ?) AS flagged_by_me,
        (SELECT COUNT(*) FROM posts p2 WHERE p2.link_hash = p.link_hash AND p2.link_hash IS NOT NULL AND p2.frozen = 0) AS reposts
        FROM posts p WHERE p.frozen = 0"""

    def agregar(rows):
        agregados = {}
        ordem = []
        for r in rows:
            chave = r["link_hash"] if r["link_hash"] else f"__post_{r['id']}"
            if chave not in agregados:
                agregados[chave] = {**r, "compartilhadores": [r["author"]], "total_compartilhado": max(1, r["reposts"] or 1), "ids": [r["id"]]}
                ordem.append(chave)
            else:
                a = agregados[chave]
                a["compartilhadores"].append(r["author"])
                a["total_compartilhado"] += 1
                a["ids"].append(r["id"])
                a["likes"] += r["likes"]
                a["comments"] += r["comments"]
                if r["liked_by_me"]: a["liked_by_me"] = 1
                if r["flagged_by_me"]: a["flagged_by_me"] = 1
        return [agregados[k] for k in ordem]

    c.execute(base_sql + " ORDER BY reposts DESC, p.created_at DESC LIMIT 40", (anon_id, anon_id))
    bloco1 = agregar([dict(x) for x in c.fetchall()])[:4]

    c.execute(base_sql + " ORDER BY likes DESC, p.created_at DESC LIMIT 40", (anon_id, anon_id))
    bloco2 = agregar([dict(x) for x in c.fetchall()])[:4]

    c.execute(base_sql + " AND p.created_at >= datetime('now', '-30 minutes') ORDER BY p.created_at DESC LIMIT 40", (anon_id, anon_id))
    bloco3 = agregar([dict(x) for x in c.fetchall()])[:4]

    c.execute(base_sql + " ORDER BY (likes*2 + reposts) DESC, p.created_at DESC LIMIT 40", (anon_id, anon_id))
    bloco4 = agregar([dict(x) for x in c.fetchall()])[:4]

    conn.close()
    return jsonify({"repostadas": bloco1, "curtidas": bloco2, "tempo_real": bloco3, "destaque": bloco4})



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
