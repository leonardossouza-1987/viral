import os, sqlite3
from flask import Blueprint, request, jsonify, abort

admin_api = Blueprint("admin_api", __name__, url_prefix="/admin-api")
TOKEN = os.getenv("ADMIN_TOKEN", "meu-token-secreto-123")

def db():
    conn = sqlite3.connect("viral.db"); conn.row_factory = sqlite3.Row; return conn

def exige_token():
    t = request.headers.get("X-Admin-Token") or request.args.get("token")
    if t != TOKEN:
        abort(404)

@admin_api.before_request
def protecao():
    exige_token()

@admin_api.route("/stats")
def stats():
    conn = db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM posts WHERE frozen = 0"); ativos = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM posts WHERE frozen = 1"); congelados = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users"); usuarios = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM flags"); flags = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM packs"); packs = c.fetchone()[0]
    conn.close()
    return jsonify({"ativos": ativos, "congelados": congelados, "usuarios": usuarios, "flags": flags, "packs": packs})

@admin_api.route("/congelados")
def congelados():
    conn = db(); c = conn.cursor()
    c.execute("SELECT id, anon_name, content, link, link_title, reports, created_at FROM posts WHERE frozen = 1 ORDER BY created_at DESC")
    rows = [dict(r) for r in c.fetchall()]; conn.close()
    return jsonify(rows)

@admin_api.route("/ativos")
def ativos():
    conn = db(); c = conn.cursor()
    c.execute("SELECT id, anon_name, content, link, link_title, reports, created_at FROM posts WHERE frozen = 0 ORDER BY created_at DESC LIMIT 100")
    rows = [dict(r) for r in c.fetchall()]; conn.close()
    return jsonify(rows)

@admin_api.route("/descongelar/<int:pid>", methods=["POST"])
def descongelar(pid):
    conn = db(); c = conn.cursor()
    c.execute("UPDATE posts SET frozen = 0, reports = 0 WHERE id = ?", (pid,))
    c.execute("DELETE FROM flags WHERE post_id = ?", (pid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@admin_api.route("/congelar/<int:pid>", methods=["POST"])
def congelar(pid):
    conn = db(); c = conn.cursor()
    c.execute("UPDATE posts SET frozen = 1 WHERE id = ?", (pid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})

@admin_api.route("/deletar/<int:pid>", methods=["POST"])
def deletar(pid):
    conn = db(); c = conn.cursor()
    c.execute("DELETE FROM posts WHERE id = ?", (pid,))
    c.execute("DELETE FROM likes WHERE post_id = ?", (pid,))
    c.execute("DELETE FROM comments WHERE post_id = ?", (pid,))
    c.execute("DELETE FROM flags WHERE post_id = ?", (pid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})
