"""Archlot 本地记忆：profile + SQLite FTS5 事实库 + 月度笔记。

设计目标：
- 完全本地，无服务、无向量库
- 事实可增删改查，冲突时作废旧事实但不丢历史
- 人类可以直接读/改 profile.md 和 notes/
"""

import contextlib
import json
import os
import re
import sqlite3
import time

from .config import MEMORY_DIR

DEFAULT_PROFILE = """# 用户档案

（这里放稳定信息：称呼、偏好、机器环境、明确要求。可以手动编辑。）
"""


def _now():
    return time.strftime("%Y-%m-%d %H:%M")


def _bigrams(text):
    text = _norm(text)
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _similar(a, b):
    """字符 bigram Jaccard，中文也能用。"""
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def _norm(text):
    text = str(text).strip().lower()
    text = re.sub(r"[\s，。！？、；：,.!?;:（）()\[\]【】\"'“”‘’]+", "", text)
    return text


class Memory:
    def __init__(self, base=None):
        self.base = os.path.abspath(os.path.expanduser(base or MEMORY_DIR))
        self.notes_dir = os.path.join(self.base, "notes")
        os.makedirs(self.notes_dir, exist_ok=True)
        self.db_path = os.path.join(self.base, "facts.db")
        self.profile_path = os.path.join(self.base, "profile.md")
        self._init_profile()
        self._init_db()

    # ---------------------------------------------------------------- 初始化

    def _init_profile(self):
        if not os.path.exists(self.profile_path):
            with open(self.profile_path, "w") as f:
                f.write(DEFAULT_PROFILE)

    @contextlib.contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=5)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=5000")
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self):
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    tags TEXT DEFAULT '',
                    created TEXT,
                    last_used TEXT,
                    status TEXT DEFAULT 'active',
                    superseded_by INTEGER,
                    source TEXT DEFAULT ''
                )
            """)
            try:
                con.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                        text, tags, tokenize='trigram'
                    )
                """)
            except sqlite3.OperationalError:
                con.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                        text, tags, tokenize='unicode61'
                    )
                """)

    # ---------------------------------------------------------------- 写入

    def add(self, text, tags="", source="", supersedes=None):
        text = str(text).strip()
        if not text:
            return None
        now = _now()
        key = _norm(text)
        with self._connect() as con:
            # 完全相同、互相包含或高度相似的，视为同一条
            for fid, old, old_tags in con.execute(
                    "SELECT id, text, tags FROM facts "
                    "WHERE status='active'").fetchall():
                old_key = _norm(old)
                if not old_key:
                    continue
                if _similar(text, old) >= 0.72 or key == old_key \
                        or key in old_key or old_key in key:
                    keep = old if len(old_key) >= len(key) else text
                    tags = ",".join(dict.fromkeys(
                        (old_tags + "," + (tags or "")).split(","))).strip(",")
                    con.execute(
                        "UPDATE facts SET text=?, tags=?, last_used=? WHERE id=?",
                        (keep, tags, now, fid))
                    con.execute(
                        "UPDATE facts_fts SET text=? WHERE rowid=?", (keep, fid))
                    return fid
            cur = con.execute(
                "INSERT INTO facts(text, tags, created, last_used, source) "
                "VALUES (?,?,?,?,?)", (text, tags, now, now, source))
            fid = cur.lastrowid
            con.execute(
                "INSERT INTO facts_fts(rowid, text, tags) VALUES (?,?,?)",
                (fid, text, tags))
            if supersedes:
                old = con.execute(
                    "SELECT id FROM facts WHERE status='active' AND text LIKE ? "
                    "ORDER BY id DESC LIMIT 1",
                    (f"%{str(supersedes).strip()}%",)).fetchone()
                if old and old[0] != fid:
                    con.execute(
                        "UPDATE facts SET status='superseded', superseded_by=? "
                        "WHERE id=?", (fid, old[0]))
        return fid

    def dedupe(self):
        """合并互相包含的事实，保留最长的，标签取并集。"""
        removed = 0
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, text, tags FROM facts WHERE status='active' "
                "ORDER BY length(text) DESC").fetchall()
            kept = []
            for fid, text, tags in rows:
                k = _norm(text)
                hit = None
                for kfid, ktext, ktags in kept:
                    kk = _norm(ktext)
                    if k and (k in kk or kk in k or _similar(text, ktext) >= 0.72):
                        hit = (kfid, ktags)
                        break
                if hit:
                    merged_tags = ",".join(
                        dict.fromkeys((hit[1] + "," + (tags or "")).split(",")))
                    con.execute("UPDATE facts SET tags=? WHERE id=?",
                                (merged_tags.strip(","), hit[0]))
                    con.execute("DELETE FROM facts WHERE id=?", (fid,))
                    con.execute("DELETE FROM facts_fts WHERE rowid=?", (fid,))
                    removed += 1
                else:
                    kept.append((fid, text, tags))
        return removed

    def consolidate(self, threshold=0.45):
        """本地聚类合并，不依赖模型：相似且同类的条目并成一条。"""
        rows = self.recent(200)
        parent = {i: i for i, _, _ in rows}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                ida, ta, taga = rows[i]
                idb, tb, tagb = rows[j]
                ca = (taga or "").split(",")[0]
                cb = (tagb or "").split(",")[0]
                if ca and cb and ca != cb:
                    continue
                if _similar(ta, tb) >= threshold:
                    union(ida, idb)

        groups = {}
        for i, _, _ in rows:
            groups.setdefault(find(i), []).append(i)
        removed = 0
        for ids in groups.values():
            if len(ids) > 1:
                removed += self.merge_ids(ids)
        return removed

    def merge_ids(self, ids):
        """把一组 id 合并成一条：保留最长的文本，标签取并集。"""
        ids = [int(i) for i in ids if str(i).isdigit()]
        if len(ids) < 2:
            return 0
        with self._connect() as con:
            marks = ",".join(["?"] * len(ids))
            rows = con.execute(
                f"SELECT id, text, tags FROM facts WHERE id IN ({marks})",
                ids).fetchall()
            if len(rows) < 2:
                return 0
            rows.sort(key=lambda r: len(r[1]), reverse=True)
            keep_id, keep_text, keep_tags = rows[0]
            tags = set()
            for _, _, t in rows:
                tags.update(x for x in (t or "").split(",") if x)
            con.execute("UPDATE facts SET text=?, tags=? WHERE id=?",
                        (keep_text, ",".join(tags), keep_id))
            con.execute("UPDATE facts_fts SET text=?, tags=? WHERE rowid=?",
                        (keep_text, ",".join(tags), keep_id))
            for fid, _, _ in rows[1:]:
                con.execute("DELETE FROM facts WHERE id=?", (fid,))
                con.execute("DELETE FROM facts_fts WHERE rowid=?", (fid,))
            return len(rows) - 1

    def forget(self, ident):
        """按 id 或文本片段真删。"""
        with self._connect() as con:
            if str(ident).isdigit():
                rows = con.execute("SELECT id FROM facts WHERE id=?",
                                   (int(ident),)).fetchall()
            else:
                rows = con.execute(
                    "SELECT id FROM facts WHERE text LIKE ?",
                    (f"%{ident}%",)).fetchall()
            for (fid,) in rows:
                con.execute("DELETE FROM facts WHERE id=?", (fid,))
                con.execute("DELETE FROM facts_fts WHERE rowid=?", (fid,))
            return len(rows)

    # ---------------------------------------------------------------- 读取

    def profile(self, limit=1200):
        try:
            with open(self.profile_path) as f:
                return f.read().strip()[:limit]
        except OSError:
            return ""

    def set_profile(self, text):
        with open(self.profile_path, "w") as f:
            f.write(str(text).strip() + "\n")

    def _terms(self, query):
        """中文没有分词，用 3 字滑窗当检索词，英文按空格切。"""
        terms = []
        for tok in re.split(r"[\s，。！？、；：,.!?;:()（）]+", str(query)):
            tok = tok.strip()
            if not tok:
                continue
            if re.search(r"[\u4e00-\u9fff]", tok):
                if len(tok) <= 3:
                    terms.append(tok)
                else:
                    for i in range(0, len(tok) - 2):
                        terms.append(tok[i:i + 3])
            elif len(tok) >= 3:
                terms.append(tok)
        seen = []
        for t in terms:
            if t not in seen:
                seen.append(t)
        return seen[:12]

    def _fts_query(self, query):
        terms = self._terms(query)
        if not terms:
            return None
        return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)

    def search(self, query, limit=6):
        query = str(query or "").strip()
        now = time.time()
        rows = []
        with self._connect() as con:
            match = self._fts_query(query)
            if match:
                try:
                    rows = con.execute("""
                        SELECT f.id, f.text, f.tags, f.last_used, bm25(facts_fts)
                        FROM facts_fts JOIN facts f ON f.id = facts_fts.rowid
                        WHERE facts_fts MATCH ? AND f.status='active'
                        ORDER BY rank LIMIT ?
                    """, (match, limit * 3)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                candidates = self._terms(query) or ([query] if query else [])
                for cand in candidates[:4]:
                    rows = con.execute("""
                        SELECT id, text, tags, last_used, 0
                        FROM facts WHERE status='active' AND text LIKE ?
                        ORDER BY last_used DESC LIMIT ?
                    """, (f"%{cand}%", limit * 3)).fetchall()
                    if rows:
                        break
                if not rows:
                    rows = con.execute("""
                        SELECT id, text, tags, last_used, 0
                        FROM facts WHERE status='active'
                        ORDER BY last_used DESC LIMIT ?
                    """, (limit * 3,)).fetchall()

        scored = []
        for fid, text, tags, last_used, rank in rows:
            try:
                ts = time.mktime(time.strptime(last_used or "", "%Y-%m-%d %H:%M"))
            except (ValueError, TypeError):
                ts = now - 86400 * 30
            age_days = max(0.0, (now - ts) / 86400)
            # bm25 越小越相关，叠加时间衰减
            score = float(rank) - age_days * 0.05
            if "经验" in (tags or ""):
                score -= 0.4  # 经验优先浮上来
            scored.append((score, fid, text, tags))
        scored.sort(key=lambda x: x[0])
        return scored[:limit]

    def touch(self, ids):
        if not ids:
            return
        now = _now()
        with self._connect() as con:
            for fid in ids:
                con.execute("UPDATE facts SET last_used=? WHERE id=?", (now, fid))

    def recent(self, limit=8):
        with self._connect() as con:
            return con.execute("""
                SELECT id, text, tags FROM facts
                WHERE status='active' ORDER BY last_used DESC LIMIT ?
            """, (limit,)).fetchall()

    def context_for(self, query, max_chars=1400):
        """拼给模型的记忆块：档案 + 相关事实。"""
        parts = []
        prof = self.profile()
        if prof:
            parts.append("[用户档案]\n" + prof)
        hits = self.search(query, limit=6) if query else []
        if hits:
            self.touch([h[1] for h in hits])
            lines = "\n".join(
                f"- [{h[3]}] {h[2]}" if h[3] else f"- {h[2]}" for h in hits)
            parts.append("[相关记忆]\n" + lines)
        text = "\n\n".join(parts)
        return text[:max_chars]

    # ---------------------------------------------------------------- 笔记

    def note(self, text):
        text = str(text).strip()
        if not text:
            return
        path = os.path.join(self.notes_dir, time.strftime("%Y-%m") + ".md")
        line = f"- {_now()} {text}\n"
        with open(path, "a") as f:
            f.write(line)

    def stats(self):
        with self._connect() as con:
            active = con.execute(
                "SELECT COUNT(*) FROM facts WHERE status='active'").fetchone()[0]
            total = con.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        notes = len(os.listdir(self.notes_dir))
        return {"active": active, "total": total, "notes_files": notes}


if __name__ == "__main__":
    m = Memory()
    print(json.dumps(m.stats(), ensure_ascii=False))
    print("profile:", m.profile()[:100] or "(空)")
    print("search:", [h[2] for h in m.search("工作区")])
