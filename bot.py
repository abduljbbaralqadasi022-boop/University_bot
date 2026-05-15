"""
بوت مكتبة الجامعة - نظام متكامل لإدارة الملفات الدراسية
المطور: Abduljbbar AL_Qdasi
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta, timezone, time as dtime
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import pandas as pd

# ============= الإعدادات الأساسية =============
TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "8825417900:AAGQ_6i5nk6XpUglRuypiXGTUbrHm2fmZC0")
OWNER_ID = int(os.environ.get("OWNER_ID", "1812586002"))
GROUP_ID = -1003709487288  # قناة البوت — ثابتة
CHANNEL_LINK = "https://t.me/+2GOhgqO8jLVlM2Y0"
DEVELOPER    = "Abduljbbar AL_Qdasi"
DB_PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "university_bot.db")
HTML         = "HTML"
KSA_TZ       = timezone(timedelta(hours=3))   # توقيت السعودية UTC+3

CATEGORIES = ["محاضرات", "ملازم", "واجبات", "اختبارات سابقة", "مشاريع"]
CAT_EMOJIS = ["📝", "📋", "✏️", "📊", "🗂"]

# ============= مسارات ملفات الإعدادات =============
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ADMINS_FILE = os.path.join(BASE_DIR, "admins.json")
JOBS_FILE   = os.path.join(BASE_DIR, "jobs.json")
DAILY_FILE  = os.path.join(BASE_DIR, "daily_msg.json")

ALL_PERMS = ["addjob", "deljob", "viewjobs", "editdaily", "delfile", "admin"]
PERM_LABELS = {
    "addjob":    "➕ إضافة مواعيد",
    "deljob":    "🗑 حذف مواعيد",
    "viewjobs":  "👁 عرض المواعيد",
    "editdaily": "✏️ تعديل اليومي",
    "delfile":   "📁 حذف ملفات",
    "admin":     "👑 إدارة كاملة",
}
DAY_NAMES = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def h(text: object) -> str:
    """تهريب النص لـ HTML"""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ====================================================================
#  نظام الأدمن والصلاحيات
# ====================================================================

def load_admins() -> dict:
    if os.path.exists(ADMINS_FILE):
        with open(ADMINS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_admins(data: dict):
    with open(ADMINS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def has_permission(user_id: int, perm: str) -> bool:
    """
    ترجع True إذا كان المستخدم مالكاً أو يملك الصلاحية المطلوبة.
    صلاحية 'admin' تعطي وصولاً كاملاً لكل الصلاحيات الأخرى.
    """
    if user_id == OWNER_ID:
        return True
    admins = load_admins()
    uid_str = str(user_id)
    if uid_str not in admins:
        return False
    user_perms = admins[uid_str].get("perms", [])
    return perm in user_perms or "admin" in user_perms


def is_any_admin(user_id: int) -> bool:
    """ترجع True إذا كان المستخدم مالكاً أو مسجلاً في admins.json"""
    if user_id == OWNER_ID:
        return True
    return str(user_id) in load_admins()


def addadmin_keyboard(selected_perms: list) -> InlineKeyboardMarkup:
    """لوحة مفاتيح اختيار صلاحيات الأدمن الجديد"""
    kb = []
    row = []
    for perm in ALL_PERMS:
        icon = "✅" if perm in selected_perms else "☐"
        row.append(InlineKeyboardButton(
            f"{icon} {PERM_LABELS[perm]}",
            callback_data=f"adm_aptoggle_{perm}"
        ))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([
        InlineKeyboardButton("💾 حفظ", callback_data="adm_apsave"),
        InlineKeyboardButton("❌ إلغاء", callback_data="adm_apcancel"),
    ])
    return InlineKeyboardMarkup(kb)


# ====================================================================
#  إدارة الوظائف المجدولة (jobs)
# ====================================================================

def load_jobs() -> list:
    if os.path.exists(JOBS_FILE):
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_jobs(jobs: list):
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def load_daily() -> dict | None:
    if os.path.exists(DAILY_FILE):
        with open(DAILY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_daily(data: dict | None):
    with open(DAILY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _next_job_id() -> str:
    """يولّد معرفاً فريداً للوظيفة"""
    jobs = load_jobs()
    existing = {int(j["id"]) for j in jobs if str(j.get("id", "")).isdigit()}
    counter = 1
    while counter in existing:
        counter += 1
    return str(counter)


async def job_send_message(context: ContextTypes.DEFAULT_TYPE):
    """دالة إرسال رسالة الوظيفة المجدولة"""
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text=context.job.data)
    except Exception as e:
        print(f"[JOB ERROR] {e}")


async def job_send_daily(context: ContextTypes.DEFAULT_TYPE):
    """دالة إرسال الرسالة اليومية"""
    try:
        await context.bot.send_message(chat_id=GROUP_ID, text=context.job.data)
    except Exception as e:
        print(f"[DAILY JOB ERROR] {e}")


def _parse_time(time_str: str) -> dtime:
    """يحوّل نص HH:MM إلى كائن time بتوقيت السعودية"""
    hh, mm = map(int, time_str.strip().split(":"))
    return dtime(hour=hh, minute=mm, tzinfo=KSA_TZ)


def restore_jobs(job_queue) -> int:
    """يعيد تسجيل كل الوظائف المحفوظة عند بدء تشغيل البوت"""
    restored = 0

    # استعادة الوظائف المجدولة
    for job_entry in load_jobs():
        try:
            t = _parse_time(job_entry["time"])
            jtype = job_entry.get("type")
            jname = f"job_{job_entry['id']}"

            if jtype == "weekly":
                job_queue.run_daily(
                    job_send_message,
                    time=t,
                    days=(int(job_entry["day"]),),
                    name=jname,
                    data=job_entry["text"],
                )
                restored += 1
            elif jtype == "once":
                when = datetime.fromisoformat(
                    f"{job_entry['date']}T{job_entry['time']}:00"
                ).replace(tzinfo=KSA_TZ)
                if when > datetime.now(tz=KSA_TZ):
                    job_queue.run_once(
                        job_send_message,
                        when=when,
                        name=jname,
                        data=job_entry["text"],
                    )
                    restored += 1
        except Exception as e:
            print(f"[RESTORE JOB ERROR] id={job_entry.get('id')}: {e}")

    # استعادة الرسالة اليومية
    daily = load_daily()
    if daily:
        try:
            t = _parse_time(daily["time"])
            job_queue.run_daily(job_send_daily, time=t, name="daily_msg", data=daily["text"])
            restored += 1
        except Exception as e:
            print(f"[RESTORE DAILY ERROR] {e}")

    return restored


# ====================================================================
#  قاعدة البيانات
# ====================================================================
SEED_DATA = {
    ("🛡", "أمن سيبراني"): {
        "المستوى 1": [
            "مقدمة في الأمن السيبراني", "التصميم المنطقي الرقمي", "برمجة C++",
            "مقدمة للحاسبات", "لغة إنجليزية 1", "لغة عربية 1",
            "تفاضل وتكامل", "جبر خطي", "ثقافة إسلامية", "أخلاقيات الحاسوب"
        ],
        "المستوى 2": [
            "هياكل البيانات والخوارزميات", "شبكات الحاسوب 1", "نظم قواعد البيانات",
            "أمنية المعلومات", "البرمجة كائنية التوجه", "أساسيات تقنيات الويب",
            "إدارة وصيانة الأنظمة", "تحليل وتصميم الخوارزميات", "احتمالات وإحصاء"
        ],
        "المستوى 3": [
            "أمن الشبكات", "التشفير", "إدارة مشاريع تقنية المعلومات",
            "البرمجة المرنة", "الذكاء الاصطناعي", "أمن قواعد البيانات",
            "اختبار الاختراق", "أمن التطبيقات", "تحليل الفيروسات"
        ],
        "المستوى 4": [
            "أمن سحابي", "الحوسبة الجنائية", "أمن إنترنت الأشياء",
            "إدارة المخاطر الأمنية", "سياسات الأمن السيبراني",
            "مشروع التخرج", "أمن الهواتف الذكية", "الهندسة الاجتماعية"
        ],
    },
    ("💻", "علوم حاسوب"): {
        "المستوى 1": [
            "مقدمة في علوم الحاسوب", "برمجة 1", "رياضيات متقطعة",
            "لغة إنجليزية", "لغة عربية", "تفاضل وتكامل", "جبر خطي", "ثقافة إسلامية"
        ],
        "المستوى 2": [
            "هياكل البيانات", "برمجة 2", "نظم تشغيل", "شبكات",
            "قواعد بيانات", "تحليل عددي", "احتمالات", "هندسة برمجيات"
        ],
        "المستوى 3": [
            "خوارزميات متقدمة", "برمجة ويب", "أمن معلومات",
            "ذكاء اصطناعي", "رسوميات حاسوب", "لغات برمجة", "مناهج بحث"
        ],
        "المستوى 4": [
            "تطوير تطبيقات", "حوسبة سحابية", "تحليل بيانات",
            "مشروع تخرج", "أخلاقيات مهنية", "إنترنت الأشياء"
        ],
    },
    ("🖥", "تقنية معلومات"): {
        "المستوى 1": [
            "مقدمة في تقنية المعلومات", "مهارات حاسوبية", "إنجليزي تقني",
            "لغة عربية", "رياضيات", "فيزياء", "مهارات تواصل"
        ],
        "المستوى 2": [
            "برمجة ويب", "قواعد بيانات", "شبكات حاسوب", "نظم تشغيل",
            "تحليل نظم", "إدارة مشاريع", "أمن معلومات"
        ],
        "المستوى 3": [
            "برمجة تطبيقات", "تطوير نظم", "ذكاء أعمال",
            "تجارة إلكترونية", "وسائط متعددة", "إدارة خوادم", "أمن شبكات"
        ],
        "المستوى 4": [
            "حوسبة سحابية", "تحليل بيانات كبير", "إدارة تقنية",
            "مشروع تخرج", "جودة برمجيات", "أخلاقيات تقنية"
        ],
    },
}


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_database():
    conn = get_conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT, first_name TEXT, last_name TEXT,
        join_date TEXT, last_active TEXT, is_blocked INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emoji TEXT DEFAULT "🏛",
        name TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS levels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dept_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level_id INTEGER NOT NULL REFERENCES levels(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dept_id INTEGER, level_id INTEGER, subject_id INTEGER,
        cat_idx INTEGER,
        file_name TEXT, telegram_file_id TEXT,
        file_size INTEGER, uploaded_by INTEGER, upload_date TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, action TEXT, details TEXT, timestamp TEXT
    )''')

    conn.commit()

    c.execute("SELECT COUNT(*) FROM departments")
    if c.fetchone()[0] == 0:
        sort_d = 0
        for (emoji, dept_name), levels_dict in SEED_DATA.items():
            c.execute("INSERT INTO departments (emoji, name, sort_order) VALUES (?,?,?)",
                      (emoji, dept_name, sort_d))
            dept_id = c.lastrowid
            sort_d += 1
            sort_l = 0
            for level_name, subjects_list in levels_dict.items():
                c.execute("INSERT INTO levels (dept_id, name, sort_order) VALUES (?,?,?)",
                          (dept_id, level_name, sort_l))
                level_id = c.lastrowid
                sort_l += 1
                for sort_s, subj_name in enumerate(subjects_list):
                    c.execute("INSERT INTO subjects (level_id, name, sort_order) VALUES (?,?,?)",
                              (level_id, subj_name, sort_s))
        conn.commit()

    conn.close()


def log_sync(user_id, action, details=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO logs (user_id, action, details, timestamp) VALUES (?,?,?,?)",
        (user_id, action, details, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def update_user_sync(user_id, username, first_name, last_name=""):
    conn = get_conn()
    now = datetime.now().isoformat()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    if c.fetchone():
        conn.execute(
            "UPDATE users SET username=?,first_name=?,last_name=?,last_active=? WHERE user_id=?",
            (username, first_name, last_name, now, user_id)
        )
    else:
        conn.execute(
            "INSERT INTO users (user_id,username,first_name,last_name,join_date,last_active,is_blocked) VALUES (?,?,?,?,?,?,0)",
            (user_id, username, first_name, last_name, now, now)
        )
    conn.commit()
    conn.close()


# ====================================================================
#  دوال استعلام قاعدة البيانات
# ====================================================================
def db_departments():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, emoji, name FROM departments ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return rows


def db_levels(dept_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name FROM levels WHERE dept_id=? ORDER BY sort_order, id", (dept_id,)
    ).fetchall()
    conn.close()
    return rows


def db_subjects(level_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, name FROM subjects WHERE level_id=? ORDER BY sort_order, id", (level_id,)
    ).fetchall()
    conn.close()
    return rows


def db_dept(dept_id):
    conn = get_conn()
    row = conn.execute("SELECT id,emoji,name FROM departments WHERE id=?", (dept_id,)).fetchone()
    conn.close()
    return row


def db_level(level_id):
    conn = get_conn()
    row = conn.execute("SELECT id,name,dept_id FROM levels WHERE id=?", (level_id,)).fetchone()
    conn.close()
    return row


def db_subject(subj_id):
    conn = get_conn()
    row = conn.execute("SELECT id,name,level_id FROM subjects WHERE id=?", (subj_id,)).fetchone()
    conn.close()
    return row


def db_swap_order(table, id1, id2):
    conn = get_conn()
    o1 = conn.execute(f"SELECT sort_order FROM {table} WHERE id=?", (id1,)).fetchone()[0]
    o2 = conn.execute(f"SELECT sort_order FROM {table} WHERE id=?", (id2,)).fetchone()[0]
    conn.execute(f"UPDATE {table} SET sort_order=? WHERE id=?", (o2, id1))
    conn.execute(f"UPDATE {table} SET sort_order=? WHERE id=?", (o1, id2))
    conn.commit()
    conn.close()


# ====================================================================
#  لوحات المفاتيح — تصفح ورفع
# ====================================================================
def main_keyboard(user_id):
    kb = [
        [InlineKeyboardButton("📚 تصفح المكتبة",  callback_data="browse")],
        [InlineKeyboardButton("📤 رفع ملف",        callback_data="upload")],
        [InlineKeyboardButton("📢 قناة المكتبة",   url=CHANNEL_LINK)],
    ]
    if is_any_admin(user_id):
        kb.append([InlineKeyboardButton("👑 لوحة الأدمن", callback_data="admin")])
    return InlineKeyboardMarkup(kb)


def departments_keyboard(mode="b"):
    depts = db_departments()
    kb = []
    for did, emoji, name in depts:
        kb.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"{mode}D{did}")])
    kb.append([InlineKeyboardButton("🔙 الرئيسية", callback_data="main")])
    return InlineKeyboardMarkup(kb)


def levels_keyboard(dept_id, mode="b"):
    levels = db_levels(dept_id)
    kb = []
    for lid, name in levels:
        kb.append([InlineKeyboardButton(f"📚 {name}", callback_data=f"{mode}L{dept_id}_{lid}")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"{mode}dept")])
    return InlineKeyboardMarkup(kb)


def subjects_keyboard(dept_id, level_id, mode="b"):
    subjs = db_subjects(level_id)
    kb = []
    for sid, name in subjs:
        kb.append([InlineKeyboardButton(f"📖 {name}", callback_data=f"{mode}S{dept_id}_{level_id}_{sid}")])
    kb.append([
        InlineKeyboardButton("🔙 رجوع", callback_data=f"{mode}D{dept_id}"),
        InlineKeyboardButton("🏠 الرئيسية", callback_data="main"),
    ])
    return InlineKeyboardMarkup(kb)


def categories_keyboard(dept_id, level_id, subj_id, mode="b"):
    kb = []
    for ci, cat in enumerate(CATEGORIES):
        kb.append([InlineKeyboardButton(f"{CAT_EMOJIS[ci]} {cat}",
                                        callback_data=f"{mode}C{dept_id}_{level_id}_{subj_id}_{ci}")])
    kb.append([
        InlineKeyboardButton("🔙 رجوع", callback_data=f"{mode}L{dept_id}_{level_id}"),
        InlineKeyboardButton("🏠 الرئيسية", callback_data="main"),
    ])
    return InlineKeyboardMarkup(kb)


def files_view_keyboard(dept_id, level_id, subj_id, ci):
    kb = [
        [InlineKeyboardButton("📤 إضافة ملف لهذا القسم",
                              callback_data=f"uC{dept_id}_{level_id}_{subj_id}_{ci}")],
        [
            InlineKeyboardButton("🔙 رجوع", callback_data=f"bS{dept_id}_{level_id}_{subj_id}"),
            InlineKeyboardButton("🏠 الرئيسية", callback_data="main"),
        ],
    ]
    return InlineKeyboardMarkup(kb)


# ====================================================================
#  لوحات المفاتيح — إدارة الأدمن
# ====================================================================
def admin_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 المستخدمون",        callback_data="adm_users")],
        [InlineKeyboardButton("📋 السجلات الأخيرة",   callback_data="adm_logs")],
        [InlineKeyboardButton("📁 آخر الملفات",        callback_data="adm_files")],
        [InlineKeyboardButton("📁 إدارة الملفات",      callback_data="adm_mfiles_0")],
        [InlineKeyboardButton("📊 تصدير Excel",        callback_data="adm_excel")],
        [InlineKeyboardButton("⚙️ إدارة الأقسام",     callback_data="adm_depts")],
        [InlineKeyboardButton("🔙 الرئيسية",           callback_data="main")],
    ])


def adm_depts_keyboard():
    depts = db_departments()
    kb = []
    for i, (did, emoji, name) in enumerate(depts):
        row = [InlineKeyboardButton(f"{emoji} {name}", callback_data=f"adm_dep_{did}")]
        if i > 0:
            row.append(InlineKeyboardButton("⬆️", callback_data=f"adm_dup_{did}"))
        if i < len(depts) - 1:
            row.append(InlineKeyboardButton("⬇️", callback_data=f"adm_ddn_{did}"))
        kb.append(row)
    kb.append([InlineKeyboardButton("➕ إضافة قسم جديد", callback_data="adm_dadd")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin")])
    return InlineKeyboardMarkup(kb)


def adm_dept_detail_keyboard(dept_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل الاسم",     callback_data=f"adm_dedit_{dept_id}")],
        [InlineKeyboardButton("🔤 تغيير الإيموجي",  callback_data=f"adm_demoji_{dept_id}")],
        [InlineKeyboardButton("📚 إدارة المستويات", callback_data=f"adm_levels_{dept_id}")],
        [InlineKeyboardButton("🗑 حذف القسم",       callback_data=f"adm_ddel_{dept_id}")],
        [InlineKeyboardButton("🔙 رجوع",            callback_data="adm_depts")],
    ])


def adm_levels_keyboard(dept_id):
    levels = db_levels(dept_id)
    kb = []
    for i, (lid, name) in enumerate(levels):
        row = [InlineKeyboardButton(f"📚 {name}", callback_data=f"adm_lev_{dept_id}_{lid}")]
        if i > 0:
            row.append(InlineKeyboardButton("⬆️", callback_data=f"adm_lup_{dept_id}_{lid}"))
        if i < len(levels) - 1:
            row.append(InlineKeyboardButton("⬇️", callback_data=f"adm_ldn_{dept_id}_{lid}"))
        kb.append(row)
    kb.append([InlineKeyboardButton("➕ إضافة مستوى", callback_data=f"adm_ladd_{dept_id}")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"adm_dep_{dept_id}")])
    return InlineKeyboardMarkup(kb)


def adm_level_detail_keyboard(dept_id, level_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل الاسم",      callback_data=f"adm_ledit_{dept_id}_{level_id}")],
        [InlineKeyboardButton("📖 إدارة المواد",      callback_data=f"adm_subjs_{dept_id}_{level_id}")],
        [InlineKeyboardButton("🗑 حذف المستوى",       callback_data=f"adm_ldel_{dept_id}_{level_id}")],
        [InlineKeyboardButton("🔙 رجوع",              callback_data=f"adm_levels_{dept_id}")],
    ])


def adm_subjects_keyboard(dept_id, level_id):
    subjs = db_subjects(level_id)
    kb = []
    for i, (sid, name) in enumerate(subjs):
        row = [InlineKeyboardButton(f"📖 {name}", callback_data=f"adm_sub_{dept_id}_{level_id}_{sid}")]
        if i > 0:
            row.append(InlineKeyboardButton("⬆️", callback_data=f"adm_sup_{dept_id}_{level_id}_{sid}"))
        if i < len(subjs) - 1:
            row.append(InlineKeyboardButton("⬇️", callback_data=f"adm_sdn_{dept_id}_{level_id}_{sid}"))
        kb.append(row)
    kb.append([InlineKeyboardButton("➕ إضافة مادة", callback_data=f"adm_sadd_{dept_id}_{level_id}")])
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"adm_lev_{dept_id}_{level_id}")])
    return InlineKeyboardMarkup(kb)


def adm_subject_detail_keyboard(dept_id, level_id, subj_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ تعديل الاسم",  callback_data=f"adm_sedit_{dept_id}_{level_id}_{subj_id}")],
        [InlineKeyboardButton("🗑 حذف المادة",    callback_data=f"adm_sdel_{dept_id}_{level_id}_{subj_id}")],
        [InlineKeyboardButton("🔙 رجوع",          callback_data=f"adm_subjs_{dept_id}_{level_id}")],
    ])


def confirm_keyboard(yes_cb, no_cb):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ نعم، احذف", callback_data=yes_cb),
         InlineKeyboardButton("❌ لا، رجوع", callback_data=no_cb)],
    ])


# ====================================================================
#  المعالجات الرئيسية
# ====================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    update_user_sync(user.id, user.username or "", user.first_name, user.last_name or "")
    log_sync(user.id, "start")

    text = (
        f"🎓 <b>أهلاً وسهلاً {h(user.first_name)}!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📚 <b>مكتبة الجامعة الرقمية</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "يمكنك من خلال هذا البوت:\n"
        "• 🔍 تصفح المواد الدراسية لجميع الأقسام\n"
        "• 📥 تحميل الملفات (محاضرات، ملازم، واجبات...)\n"
        "• 📤 رفع ومشاركة ملفاتك مع زملائك\n\n"
        "📢 انضم لقناتنا (اختياري):\n"
        f"{CHANNEL_LINK}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"👨‍💻 <b>المطور:</b> {h(DEVELOPER)}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(text, reply_markup=main_keyboard(user.id), parse_mode=HTML)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user  = update.effective_user
    data  = query.data

    update_user_sync(user.id, user.username or "", user.first_name, user.last_name or "")

    # ── الرئيسية ──
    if data == "main":
        context.user_data.clear()
        await query.edit_message_text(
            "🎓 <b>القائمة الرئيسية</b>", reply_markup=main_keyboard(user.id), parse_mode=HTML
        )
        return

    # ── تصفح ──
    if data == "browse":
        context.user_data.clear()
        await query.edit_message_text("🏛 <b>اختر القسم:</b>",
                                      reply_markup=departments_keyboard("b"), parse_mode=HTML)
        return

    # ── رفع ──
    if data == "upload":
        context.user_data.clear()
        await query.edit_message_text("📤 <b>رفع ملف — اختر القسم:</b>",
                                      reply_markup=departments_keyboard("u"), parse_mode=HTML)
        return

    # ── رجوع للأقسام ──
    if data in ("bdept", "udept"):
        mode = data[0]
        txt = "📤 <b>رفع ملف — اختر القسم:</b>" if mode == "u" else "🏛 <b>اختر القسم:</b>"
        await query.edit_message_text(txt, reply_markup=departments_keyboard(mode), parse_mode=HTML)
        return

    # ── اختيار قسم ──
    if data.startswith("bD") or data.startswith("uD"):
        mode, dept_id = data[0], int(data[2:])
        dept = db_dept(dept_id)
        if not dept:
            await query.edit_message_text("❌ القسم غير موجود.", reply_markup=main_keyboard(user.id), parse_mode=HTML)
            return
        _, emoji, name = dept
        prefix = "📤 <b>رفع ملف — " if mode == "u" else ""
        suffix = "</b>" if mode == "u" else ""
        await query.edit_message_text(
            f"{emoji} <b>{h(name)}</b>{suffix}\n\nاختر المستوى:",
            reply_markup=levels_keyboard(dept_id, mode), parse_mode=HTML
        )
        return

    # ── اختيار مستوى ──
    if (data.startswith("bL") or data.startswith("uL")) and data.count("_") == 1:
        mode = data[0]
        parts = data[2:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        dept  = db_dept(dept_id)
        level = db_level(level_id)
        if not dept or not level:
            await query.edit_message_text("❌ البيانات غير موجودة.", parse_mode=HTML)
            return
        _, emoji, dname = dept
        _, lname, _ = level
        await query.edit_message_text(
            f"{emoji} <b>{h(dname)} | {h(lname)}</b>\n\nاختر المادة:",
            reply_markup=subjects_keyboard(dept_id, level_id, mode), parse_mode=HTML
        )
        return

    # ── اختيار مادة ──
    if (data.startswith("bS") or data.startswith("uS")) and "_" in data:
        mode = data[0]
        parts = data[2:].split("_")
        dept_id, level_id, subj_id = int(parts[0]), int(parts[1]), int(parts[2])
        subj = db_subject(subj_id)
        if not subj:
            await query.edit_message_text("❌ المادة غير موجودة.", parse_mode=HTML)
            return
        _, sname, _ = subj
        await query.edit_message_text(
            f"📖 <b>{h(sname)}</b>\n\nاختر نوع الملف:",
            reply_markup=categories_keyboard(dept_id, level_id, subj_id, mode), parse_mode=HTML
        )
        return

    # ── عرض الملفات ──
    if data.startswith("bC") and "_" in data:
        parts = data[2:].split("_")
        dept_id, level_id, subj_id, ci = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        subj = db_subject(subj_id)
        sname = subj[1] if subj else "؟"
        cat   = CATEGORIES[ci]
        log_sync(user.id, "browse", f"{sname}-{cat}")

        conn = get_conn()
        files = conn.execute(
            "SELECT file_name, telegram_file_id FROM files WHERE dept_id=? AND level_id=? AND subject_id=? AND cat_idx=?",
            (dept_id, level_id, subj_id, ci)
        ).fetchall()
        conn.close()

        if files:
            await query.edit_message_text(
                f"📂 <b>{h(sname)} | {h(cat)}</b>\n\n✅ يوجد <b>{len(files)}</b> ملف، جاري الإرسال...",
                reply_markup=files_view_keyboard(dept_id, level_id, subj_id, ci), parse_mode=HTML
            )
            for fname, fid in files:
                try:
                    await context.bot.send_document(chat_id=user.id, document=fid,
                                                    caption=f"📄 {fname}\n📂 {sname} | {cat}")
                except Exception:
                    await query.message.reply_text(f"⚠️ تعذّر إرسال: {fname}")
        else:
            await query.edit_message_text(
                f"📂 <b>{h(sname)} | {h(cat)}</b>\n\n❌ لا توجد ملفات بعد.\n\nكن أول من يساهم! 👇",
                reply_markup=files_view_keyboard(dept_id, level_id, subj_id, ci), parse_mode=HTML
            )
        return

    # ── رجوع لقائمة المواد (من صفحة عرض الملفات، مع 3 شرطات) ──
    if data.startswith("bL") and data.count("_") == 2:
        parts = data[2:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        dept  = db_dept(dept_id)
        level = db_level(level_id)
        _, emoji, dname = dept or (0, "🏛", "؟")
        _, lname, _     = level or (0, "؟", 0)
        await query.edit_message_text(
            f"{emoji} <b>{h(dname)} | {h(lname)}</b>\n\nاختر المادة:",
            reply_markup=subjects_keyboard(dept_id, level_id, "b"), parse_mode=HTML
        )
        return

    # ── إضافة ملف مباشرةً لقسم محدد ──
    if data.startswith("uC") and "_" in data:
        parts = data[2:].split("_")
        dept_id, level_id, subj_id, ci = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        subj  = db_subject(subj_id)
        dept  = db_dept(dept_id)
        level = db_level(level_id)
        sname = subj[1]  if subj  else "؟"
        dname = dept[2]  if dept  else "؟"
        lname = level[1] if level else "؟"
        cat   = CATEGORIES[ci]

        context.user_data.update({
            "awaiting_file": True,
            "dept_id": dept_id, "level_id": level_id,
            "subj_id": subj_id, "ci": ci,
        })
        await query.edit_message_text(
            f"📤 <b>رفع ملف</b>\n\n"
            f"📂 {h(dname)} ‹ {h(lname)} ‹ {h(sname)} ‹ {h(cat)}\n\n"
            "✅ أرسل الملف الآن:", parse_mode=HTML
        )
        return

    # ==================================================================
    #  لوحة الأدمن — يجب أن يكون المستخدم أدمناً
    # ==================================================================
    if not is_any_admin(user.id):
        return

    # ── لوحة الأدمن الرئيسية ──
    if data == "admin":
        await _admin_main(query)
        return

    # ── صلاحيات: إدارة كاملة ──
    if data == "adm_users":
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        await _adm_users(query)
        return

    if data == "adm_logs":
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        await _adm_logs(query)
        return

    if data == "adm_files":
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        await _adm_files(query)
        return

    if data == "adm_excel":
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        await _adm_excel(query, context, user.id)
        return

    # ── إدارة الملفات مع pagination ──
    if data.startswith("adm_mfiles_"):
        if not has_permission(user.id, "delfile"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        page = int(data.split("_")[-1])
        await _adm_manage_files(query, page)
        return

    # ── حذف ملف (تأكيد) ──
    if data.startswith("adm_dfile_"):
        if not has_permission(user.id, "delfile"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data.split("_")
        file_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        conn = get_conn()
        row = conn.execute("SELECT file_name FROM files WHERE id=?", (file_id,)).fetchone()
        conn.close()
        fname = row[0] if row else "؟"
        await query.edit_message_text(
            f"⚠️ هل تريد حذف الملف:\n<b>{h(fname)}</b>؟",
            reply_markup=confirm_keyboard(
                f"adm_dfileok_{file_id}_{page}",
                f"adm_mfiles_{page}"
            ),
            parse_mode=HTML
        )
        return

    # ── تأكيد حذف الملف ──
    if data.startswith("adm_dfileok_"):
        if not has_permission(user.id, "delfile"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data.split("_")
        file_id = int(parts[2])
        page = int(parts[3]) if len(parts) > 3 else 0
        conn = get_conn()
        conn.execute("DELETE FROM files WHERE id=?", (file_id,))
        conn.commit()
        conn.close()
        log_sync(user.id, "delete_file", f"file_id={file_id}")
        await query.answer("✅ تم حذف الملف", show_alert=False)
        await _adm_manage_files(query, page)
        return

    # ==================================================================
    #  إضافة أدمن — للمالك فقط
    # ==================================================================
    if data.startswith("adm_aptoggle_"):
        if user.id != OWNER_ID:
            await query.answer("هذا الأمر للمالك فقط ❌", show_alert=True)
            return
        perm = data.split("adm_aptoggle_")[1]
        if "pa_perms" not in context.user_data:
            context.user_data["pa_perms"] = []
        perms = context.user_data["pa_perms"]
        if perm in perms:
            perms.remove(perm)
        else:
            perms.append(perm)
        context.user_data["pa_perms"] = perms
        pa_id = context.user_data.get("pa_id", "؟")
        await query.edit_message_text(
            f"👤 إضافة أدمن: <code>{pa_id}</code>\n\nاختر الصلاحيات:",
            reply_markup=addadmin_keyboard(perms),
            parse_mode=HTML
        )
        return

    if data == "adm_apsave":
        if user.id != OWNER_ID:
            await query.answer("هذا الأمر للمالك فقط ❌", show_alert=True)
            return
        pa_id = context.user_data.get("pa_id")
        pa_perms = context.user_data.get("pa_perms", [])
        if not pa_id:
            await query.answer("انتهت الجلسة، أعد المحاولة", show_alert=True)
            return
        admins = load_admins()
        admins[str(pa_id)] = {"perms": pa_perms, "added_by": user.id, "date": datetime.now().isoformat()}
        save_admins(admins)
        context.user_data.pop("pa_id", None)
        context.user_data.pop("pa_perms", None)
        perms_text = ", ".join(pa_perms) if pa_perms else "بدون صلاحيات"
        await query.edit_message_text(
            f"✅ تم إضافة الأدمن <code>{pa_id}</code>\n"
            f"📋 الصلاحيات: {h(perms_text)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]]),
            parse_mode=HTML
        )
        return

    if data == "adm_apcancel":
        if user.id != OWNER_ID:
            return
        context.user_data.pop("pa_id", None)
        context.user_data.pop("pa_perms", None)
        await query.edit_message_text(
            "❌ تم إلغاء العملية.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
        )
        return

    # ── قائمة الأقسام ──
    if data == "adm_depts":
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        await query.edit_message_text(
            "⚙️ <b>إدارة الأقسام</b>\n\nاضغط على قسم لتعديله أو استخدم الأسهم لإعادة الترتيب:",
            reply_markup=adm_depts_keyboard(), parse_mode=HTML
        )
        return

    # ── تفاصيل قسم ──
    if data.startswith("adm_dep_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id = int(data.split("_")[-1])
        dept = db_dept(dept_id)
        if not dept:
            await query.answer("القسم غير موجود!", show_alert=True)
            return
        _, emoji, name = dept
        await query.edit_message_text(
            f"{emoji} <b>{h(name)}</b>\n\nماذا تريد أن تفعل؟",
            reply_markup=adm_dept_detail_keyboard(dept_id), parse_mode=HTML
        )
        return

    # ── تعديل اسم القسم ──
    if data.startswith("adm_dedit_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id = int(data.split("_")[-1])
        context.user_data["admin_action"] = "edit_dept"
        context.user_data["admin_target"]  = dept_id
        dept = db_dept(dept_id)
        await query.edit_message_text(
            f"✏️ أرسل الاسم الجديد للقسم <b>{h(dept[2]) if dept else ''}</b>:",
            parse_mode=HTML
        )
        return

    # ── تغيير إيموجي القسم ──
    if data.startswith("adm_demoji_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id = int(data.split("_")[-1])
        context.user_data["admin_action"] = "edit_dept_emoji"
        context.user_data["admin_target"]  = dept_id
        await query.edit_message_text("🔤 أرسل الإيموجي الجديد للقسم:", parse_mode=HTML)
        return

    # ── إضافة قسم ──
    if data == "adm_dadd":
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        context.user_data["admin_action"] = "add_dept"
        await query.edit_message_text(
            "➕ أرسل اسم القسم الجديد:\n(سيُضاف بإيموجي 🏛 افتراضي، يمكنك تغييره لاحقاً)", parse_mode=HTML
        )
        return

    # ── حذف قسم (تأكيد) ──
    if data.startswith("adm_ddel_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id = int(data.split("_")[-1])
        dept = db_dept(dept_id)
        name = dept[2] if dept else "؟"
        await query.edit_message_text(
            f"⚠️ هل أنت متأكد من حذف قسم <b>{h(name)}</b> وجميع ما فيه؟",
            reply_markup=confirm_keyboard(f"adm_ddelok_{dept_id}", f"adm_dep_{dept_id}"),
            parse_mode=HTML
        )
        return

    # ── تأكيد الحذف ──
    if data.startswith("adm_ddelok_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id = int(data.split("_")[-1])
        conn = get_conn()
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM departments WHERE id=?", (dept_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(
            "✅ تم حذف القسم.", reply_markup=adm_depts_keyboard(), parse_mode=HTML
        )
        return

    # ── تحريك قسم للأعلى / الأسفل ──
    if data.startswith("adm_dup_") or data.startswith("adm_ddn_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id  = int(data.split("_")[-1])
        depts    = db_departments()
        ids      = [r[0] for r in depts]
        idx      = ids.index(dept_id) if dept_id in ids else -1
        if data.startswith("adm_dup_") and idx > 0:
            db_swap_order("departments", dept_id, ids[idx - 1])
        elif data.startswith("adm_ddn_") and 0 <= idx < len(ids) - 1:
            db_swap_order("departments", dept_id, ids[idx + 1])
        await query.edit_message_text(
            "⚙️ <b>إدارة الأقسام</b>",
            reply_markup=adm_depts_keyboard(), parse_mode=HTML
        )
        return

    # ── قائمة المستويات ──
    if data.startswith("adm_levels_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id = int(data.split("_")[-1])
        dept = db_dept(dept_id)
        name = dept[2] if dept else "؟"
        await query.edit_message_text(
            f"📚 <b>مستويات {h(name)}</b>:",
            reply_markup=adm_levels_keyboard(dept_id), parse_mode=HTML
        )
        return

    # ── تفاصيل مستوى ──
    if data.startswith("adm_lev_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[8:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        level = db_level(level_id)
        name = level[1] if level else "؟"
        await query.edit_message_text(
            f"📚 <b>{h(name)}</b>\n\nماذا تريد؟",
            reply_markup=adm_level_detail_keyboard(dept_id, level_id), parse_mode=HTML
        )
        return

    # ── تعديل اسم مستوى ──
    if data.startswith("adm_ledit_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[10:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        context.user_data.update({"admin_action": "edit_level", "admin_target": level_id, "admin_dept": dept_id})
        level = db_level(level_id)
        await query.edit_message_text(
            f"✏️ أرسل الاسم الجديد للمستوى <b>{h(level[1]) if level else ''}</b>:", parse_mode=HTML
        )
        return

    # ── إضافة مستوى ──
    if data.startswith("adm_ladd_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        dept_id = int(data.split("_")[-1])
        context.user_data.update({"admin_action": "add_level", "admin_target": dept_id})
        await query.edit_message_text("➕ أرسل اسم المستوى الجديد:", parse_mode=HTML)
        return

    # ── حذف مستوى ──
    if data.startswith("adm_ldel_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[9:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        level = db_level(level_id)
        name = level[1] if level else "؟"
        await query.edit_message_text(
            f"⚠️ حذف المستوى <b>{h(name)}</b> وجميع مواده؟",
            reply_markup=confirm_keyboard(f"adm_ldelok_{dept_id}_{level_id}", f"adm_lev_{dept_id}_{level_id}"),
            parse_mode=HTML
        )
        return

    if data.startswith("adm_ldelok_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[11:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        conn = get_conn()
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM levels WHERE id=?", (level_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(
            "✅ تم حذف المستوى.",
            reply_markup=adm_levels_keyboard(dept_id), parse_mode=HTML
        )
        return

    # ── تحريك مستوى ──
    if data.startswith("adm_lup_") or data.startswith("adm_ldn_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[8:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        levels = db_levels(dept_id)
        ids    = [r[0] for r in levels]
        idx    = ids.index(level_id) if level_id in ids else -1
        if data.startswith("adm_lup_") and idx > 0:
            db_swap_order("levels", level_id, ids[idx - 1])
        elif data.startswith("adm_ldn_") and 0 <= idx < len(ids) - 1:
            db_swap_order("levels", level_id, ids[idx + 1])
        dept = db_dept(dept_id)
        name = dept[2] if dept else "؟"
        await query.edit_message_text(
            f"📚 <b>مستويات {h(name)}</b>:",
            reply_markup=adm_levels_keyboard(dept_id), parse_mode=HTML
        )
        return

    # ── قائمة المواد ──
    if data.startswith("adm_subjs_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[10:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        level = db_level(level_id)
        name = level[1] if level else "؟"
        await query.edit_message_text(
            f"📖 <b>مواد {h(name)}</b>:",
            reply_markup=adm_subjects_keyboard(dept_id, level_id), parse_mode=HTML
        )
        return

    # ── تفاصيل مادة ──
    if data.startswith("adm_sub_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[8:].split("_")
        dept_id, level_id, subj_id = int(parts[0]), int(parts[1]), int(parts[2])
        subj = db_subject(subj_id)
        name = subj[1] if subj else "؟"
        await query.edit_message_text(
            f"📖 <b>{h(name)}</b>\n\nماذا تريد؟",
            reply_markup=adm_subject_detail_keyboard(dept_id, level_id, subj_id), parse_mode=HTML
        )
        return

    # ── تعديل اسم مادة ──
    if data.startswith("adm_sedit_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[10:].split("_")
        dept_id, level_id, subj_id = int(parts[0]), int(parts[1]), int(parts[2])
        context.user_data.update({
            "admin_action": "edit_subject",
            "admin_target": subj_id,
            "admin_dept": dept_id, "admin_level": level_id
        })
        subj = db_subject(subj_id)
        await query.edit_message_text(
            f"✏️ أرسل الاسم الجديد للمادة <b>{h(subj[1]) if subj else ''}</b>:", parse_mode=HTML
        )
        return

    # ── إضافة مادة ──
    if data.startswith("adm_sadd_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[9:].split("_")
        dept_id, level_id = int(parts[0]), int(parts[1])
        context.user_data.update({
            "admin_action": "add_subject",
            "admin_target": level_id,
            "admin_dept": dept_id, "admin_level": level_id
        })
        await query.edit_message_text("➕ أرسل اسم المادة الجديدة:", parse_mode=HTML)
        return

    # ── حذف مادة ──
    if data.startswith("adm_sdel_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[9:].split("_")
        dept_id, level_id, subj_id = int(parts[0]), int(parts[1]), int(parts[2])
        subj = db_subject(subj_id)
        name = subj[1] if subj else "؟"
        await query.edit_message_text(
            f"⚠️ حذف المادة <b>{h(name)}</b>؟",
            reply_markup=confirm_keyboard(
                f"adm_sdelok_{dept_id}_{level_id}_{subj_id}",
                f"adm_sub_{dept_id}_{level_id}_{subj_id}"
            ), parse_mode=HTML
        )
        return

    if data.startswith("adm_sdelok_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[11:].split("_")
        dept_id, level_id, subj_id = int(parts[0]), int(parts[1]), int(parts[2])
        conn = get_conn()
        conn.execute("DELETE FROM subjects WHERE id=?", (subj_id,))
        conn.commit()
        conn.close()
        await query.edit_message_text(
            "✅ تم حذف المادة.",
            reply_markup=adm_subjects_keyboard(dept_id, level_id), parse_mode=HTML
        )
        return

    # ── تحريك مادة ──
    if data.startswith("adm_sup_") or data.startswith("adm_sdn_"):
        if not has_permission(user.id, "admin"):
            await query.answer("ما عندك صلاحية ❌", show_alert=True)
            return
        parts = data[8:].split("_")
        dept_id, level_id, subj_id = int(parts[0]), int(parts[1]), int(parts[2])
        subjs = db_subjects(level_id)
        ids   = [r[0] for r in subjs]
        idx   = ids.index(subj_id) if subj_id in ids else -1
        if data.startswith("adm_sup_") and idx > 0:
            db_swap_order("subjects", subj_id, ids[idx - 1])
        elif data.startswith("adm_sdn_") and 0 <= idx < len(ids) - 1:
            db_swap_order("subjects", subj_id, ids[idx + 1])
        level = db_level(level_id)
        name = level[1] if level else "؟"
        await query.edit_message_text(
            f"📖 <b>مواد {h(name)}</b>:",
            reply_markup=adm_subjects_keyboard(dept_id, level_id), parse_mode=HTML
        )
        return


# ====================================================================
#  إحصائيات الأدمن
# ====================================================================
async def _admin_main(query):
    conn = get_conn()
    total_users  = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    blocked      = conn.execute("SELECT COUNT(*) FROM users WHERE is_blocked=1").fetchone()[0]
    day_ago      = (datetime.now() - timedelta(hours=24)).isoformat()
    week_ago     = (datetime.now() - timedelta(days=7)).isoformat()
    active_24h   = conn.execute("SELECT COUNT(*) FROM users WHERE last_active>?", (day_ago,)).fetchone()[0]
    new_week     = conn.execute("SELECT COUNT(*) FROM users WHERE join_date>?",   (week_ago,)).fetchone()[0]
    total_files  = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    total_logs   = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
    logs_24h     = conn.execute("SELECT COUNT(*) FROM logs WHERE timestamp>?",    (day_ago,)).fetchone()[0]
    total_depts  = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
    conn.close()

    admins_count = len(load_admins())
    jobs_count   = len(load_jobs())
    has_daily    = "✅" if load_daily() else "❌"

    text = (
        "👑 <b>لوحة تحكم الأدمن</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "👥 <b>المستخدمون:</b>\n"
        f"• الإجمالي: <code>{total_users}</code>  |  نشطاء 24h: <code>{active_24h}</code>\n"
        f"• هذا الأسبوع: <code>{new_week}</code>  |  محظورون: <code>{blocked}</code>\n\n"
        f"📁 <b>الملفات:</b> <code>{total_files}</code>\n"
        f"🏛 <b>الأقسام:</b> <code>{total_depts}</code>\n\n"
        f"📋 <b>السجلات:</b> إجمالي <code>{total_logs}</code>  |  24h: <code>{logs_24h}</code>\n\n"
        f"👤 <b>الأدمن:</b> <code>{admins_count}</code>  |  "
        f"⏰ <b>المواعيد:</b> <code>{jobs_count}</code>  |  يومي: {has_daily}"
    )

    await query.edit_message_text(text, reply_markup=admin_main_keyboard(), parse_mode=HTML)


async def _adm_users(query):
    conn = get_conn()
    rows = conn.execute(
        "SELECT user_id,first_name,username,join_date,last_active FROM users ORDER BY join_date DESC LIMIT 15"
    ).fetchall()
    conn.close()
    lines = ["👥 <b>آخر 15 مستخدم:</b>\n"]
    for uid, fname, uname, jd, la in rows:
        lines.append(
            f"• <b>{h(fname or '')}</b> (@{h(uname or '—')})\n"
            f"  🆔 <code>{uid}</code> | انضم: {(jd or '')[:10]} | نشط: {(la or '')[:10]}"
        )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=HTML)


async def _adm_logs(query):
    conn = get_conn()
    rows = conn.execute(
        "SELECT l.user_id,u.first_name,l.action,l.timestamp "
        "FROM logs l LEFT JOIN users u ON l.user_id=u.user_id "
        "ORDER BY l.timestamp DESC LIMIT 20"
    ).fetchall()
    conn.close()
    labels = {"start": "▶️ بدأ", "browse": "🔍 تصفّح", "upload_file": "📤 رفع", "click": "👆 ضغط", "delete_file": "🗑 حذف ملف"}
    lines = ["📋 <b>آخر 20 نشاط:</b>\n"]
    for uid, fname, action, ts in rows:
        lines.append(f"• {h(fname or str(uid))} | {labels.get(action, action)} | {(ts or '')[11:16]}")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=HTML)


async def _adm_files(query):
    conn = get_conn()
    rows = conn.execute(
        "SELECT f.file_name,d.name,s.name,f.cat_idx,f.upload_date "
        "FROM files f "
        "LEFT JOIN departments d ON f.dept_id=d.id "
        "LEFT JOIN subjects s ON f.subject_id=s.id "
        "ORDER BY f.upload_date DESC LIMIT 20"
    ).fetchall()
    conn.close()
    if not rows:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
        await query.edit_message_text("📁 لا توجد ملفات.", reply_markup=kb, parse_mode=HTML)
        return
    lines = ["📁 <b>آخر 20 ملف:</b>\n"]
    for fname, dname, sname, ci, udate in rows:
        cat = CATEGORIES[ci] if ci is not None and 0 <= ci < len(CATEGORIES) else "؟"
        lines.append(f"• <b>{h(fname)}</b> | {h(dname or '؟')} | {h(sname or '؟')} | {h(cat)} | {(udate or '')[:10]}")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
    await query.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode=HTML)


async def _adm_manage_files(query, page: int = 0):
    """إدارة الملفات مع pagination — 10 ملفات لكل صفحة"""
    PAGE_SIZE = 10
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    rows = conn.execute(
        "SELECT f.id, f.file_name, d.name, s.name "
        "FROM files f "
        "LEFT JOIN departments d ON f.dept_id=d.id "
        "LEFT JOIN subjects s ON f.subject_id=s.id "
        "ORDER BY f.upload_date DESC LIMIT ? OFFSET ?",
        (PAGE_SIZE, page * PAGE_SIZE)
    ).fetchall()
    conn.close()

    if not rows:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
        await query.edit_message_text("📁 لا توجد ملفات.", reply_markup=kb, parse_mode=HTML)
        return

    kb = []
    for fid, fname, dname, sname in rows:
        short_name = fname[:28] + "…" if fname and len(fname) > 28 else (fname or "—")
        kb.append([
            InlineKeyboardButton(f"📄 {short_name}", callback_data="noop"),
            InlineKeyboardButton("🗑 حذف", callback_data=f"adm_dfile_{fid}_{page}"),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ السابق", callback_data=f"adm_mfiles_{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("▶️ التالي", callback_data=f"adm_mfiles_{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin")])

    total_pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    await query.edit_message_text(
        f"📁 <b>إدارة الملفات</b>\n\n"
        f"الإجمالي: <code>{total}</code> ملف | الصفحة <code>{page + 1}</code>/<code>{total_pages}</code>",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode=HTML
    )


async def _adm_excel(query, context, user_id):
    await query.edit_message_text("⏳ جاري التصدير...")
    conn = get_conn()
    users_df = pd.read_sql_query("SELECT * FROM users", conn)
    logs_df  = pd.read_sql_query("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 2000", conn)
    files_df = pd.read_sql_query(
        "SELECT f.*,d.name dept_name,l.name level_name,s.name subject_name "
        "FROM files f "
        "LEFT JOIN departments d ON f.dept_id=d.id "
        "LEFT JOIN levels l ON f.level_id=l.id "
        "LEFT JOIN subjects s ON f.subject_id=s.id", conn
    )
    depts_df = pd.read_sql_query(
        "SELECT d.emoji,d.name dept,l.name level_name,s.name subject "
        "FROM departments d "
        "LEFT JOIN levels l ON l.dept_id=d.id "
        "LEFT JOIN subjects s ON s.level_id=l.id "
        "ORDER BY d.sort_order,l.sort_order,s.sort_order", conn
    )
    conn.close()

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        users_df.to_excel(writer, sheet_name="المستخدمين", index=False)
        logs_df.to_excel(writer,  sheet_name="السجلات",    index=False)
        files_df.to_excel(writer, sheet_name="الملفات",    index=False)
        depts_df.to_excel(writer, sheet_name="هيكل الأقسام", index=False)
    output.seek(0)

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin")]])
    await query.edit_message_text("✅ جاري إرسال الملف...", reply_markup=kb)
    await context.bot.send_document(
        chat_id=user_id,
        document=output,
        filename=f"library_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        caption=f"📊 تقرير المكتبة\n👨‍💻 {DEVELOPER}"
    )


# ====================================================================
#  معالجات الأوامر الجديدة
# ====================================================================

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addadmin 123456789
    يعرض لوحة اختيار الصلاحيات للمستخدم المحدد.
    للمالك فقط.
    """
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("ما عندك صلاحية ❌")
        return

    if not context.args:
        await update.message.reply_text("الاستخدام: /addadmin <user_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ معرف المستخدم يجب أن يكون رقماً صحيحاً.")
        return

    if target_id == OWNER_ID:
        await update.message.reply_text("❌ المالك لديه كل الصلاحيات مسبقاً.")
        return

    # تحميل الصلاحيات الموجودة إن كان مسجلاً مسبقاً
    existing_perms = load_admins().get(str(target_id), {}).get("perms", [])
    context.user_data["pa_id"]    = target_id
    context.user_data["pa_perms"] = list(existing_perms)

    await update.message.reply_text(
        f"👤 إضافة/تعديل أدمن: <code>{target_id}</code>\n\nاختر الصلاحيات:",
        reply_markup=addadmin_keyboard(existing_perms),
        parse_mode=HTML
    )


async def addjob_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addjob <يوم_0-6> <HH:MM> <نص الرسالة>
    يضيف موعداً أسبوعياً يُرسل فيه رسالة للقناة.
    0=اثنين ... 6=أحد
    """
    user = update.effective_user
    if not has_permission(user.id, "addjob"):
        await update.message.reply_text("ما عندك صلاحية ❌")
        return

    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "الاستخدام: /addjob <0-6> <HH:MM> <نص الرسالة>\n"
            "مثال: /addjob 0 21:00 مرحباً بالجميع!"
        )
        return

    try:
        day = int(args[0])
        if not (0 <= day <= 6):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ اليوم يجب أن يكون بين 0 (اثنين) و 6 (أحد).")
        return

    try:
        t = _parse_time(args[1])
    except Exception:
        await update.message.reply_text("❌ تنسيق الوقت غير صحيح. استخدم: HH:MM")
        return

    text = " ".join(args[2:])
    job_id = _next_job_id()

    jobs = load_jobs()
    jobs.append({
        "id":   job_id,
        "type": "weekly",
        "day":  day,
        "time": args[1],
        "text": text,
    })
    save_jobs(jobs)

    context.job_queue.run_daily(
        job_send_message,
        time=t,
        days=(day,),
        name=f"job_{job_id}",
        data=text,
    )

    await update.message.reply_text(
        f"✅ <b>تم إضافة موعد أسبوعي</b>\n\n"
        f"🆔 المعرف: <code>{job_id}</code>\n"
        f"📅 اليوم: {DAY_NAMES[day]}\n"
        f"⏰ الوقت: {args[1]} (توقيت السعودية)\n"
        f"📝 الرسالة: {h(text[:80])}{'…' if len(text) > 80 else ''}",
        parse_mode=HTML
    )


async def oncejob_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /oncejob <YYYY-MM-DD> <HH:MM> <نص الرسالة>
    يرسل رسالة مرة واحدة في التاريخ والوقت المحدد.
    """
    user = update.effective_user
    if not has_permission(user.id, "addjob"):
        await update.message.reply_text("ما عندك صلاحية ❌")
        return

    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "الاستخدام: /oncejob <YYYY-MM-DD> <HH:MM> <نص الرسالة>\n"
            "مثال: /oncejob 2026-10-20 21:00 تذكير مهم!"
        )
        return

    date_str = args[0]
    time_str = args[1]
    text = " ".join(args[2:])

    try:
        when = datetime.fromisoformat(f"{date_str}T{time_str}:00").replace(tzinfo=KSA_TZ)
    except Exception:
        await update.message.reply_text("❌ تنسيق التاريخ أو الوقت غير صحيح.\nالصحيح: YYYY-MM-DD HH:MM")
        return

    if when <= datetime.now(tz=KSA_TZ):
        await update.message.reply_text("❌ التاريخ والوقت المحددان قد مضيا!")
        return

    job_id = _next_job_id()
    jobs = load_jobs()
    jobs.append({
        "id":   job_id,
        "type": "once",
        "date": date_str,
        "time": time_str,
        "text": text,
    })
    save_jobs(jobs)

    context.job_queue.run_once(
        job_send_message,
        when=when,
        name=f"job_{job_id}",
        data=text,
    )

    await update.message.reply_text(
        f"✅ <b>تم إضافة موعد لمرة واحدة</b>\n\n"
        f"🆔 المعرف: <code>{job_id}</code>\n"
        f"📅 التاريخ: {date_str}\n"
        f"⏰ الوقت: {time_str} (توقيت السعودية)\n"
        f"📝 الرسالة: {h(text[:80])}{'…' if len(text) > 80 else ''}",
        parse_mode=HTML
    )


async def setdaily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /setdaily <HH:MM> <نص الرسالة>
    يضبط رسالة يومية تُرسل تلقائياً كل يوم للقناة.
    تُحفظ في daily_msg.json وتُستعاد عند إعادة التشغيل.
    """
    user = update.effective_user
    if not has_permission(user.id, "editdaily"):
        await update.message.reply_text("ما عندك صلاحية ❌")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "الاستخدام: /setdaily <HH:MM> <نص الرسالة>\n"
            "مثال: /setdaily 09:00 صباح الخير! 🌞"
        )
        return

    time_str = args[0]
    text = " ".join(args[1:])

    try:
        t = _parse_time(time_str)
    except Exception:
        await update.message.reply_text("❌ تنسيق الوقت غير صحيح. استخدم: HH:MM")
        return

    # إلغاء الرسالة اليومية القديمة إن وُجدت
    old_jobs = context.job_queue.get_jobs_by_name("daily_msg")
    for job in old_jobs:
        job.schedule_removal()

    # حفظ الرسالة اليومية الجديدة
    save_daily({"time": time_str, "text": text})

    # تشغيل الوظيفة الجديدة
    context.job_queue.run_daily(job_send_daily, time=t, name="daily_msg", data=text)

    await update.message.reply_text(
        f"✅ <b>تم ضبط الرسالة اليومية</b>\n\n"
        f"⏰ الوقت: {time_str} (توقيت السعودية)\n"
        f"📝 الرسالة: {h(text[:80])}{'…' if len(text) > 80 else ''}",
        parse_mode=HTML
    )


async def deljob_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /deljob <معرف_الموعد>
    يحذف موعداً معيناً بمعرّفه (ظاهر في /listjobs).
    """
    user = update.effective_user
    if not has_permission(user.id, "deljob"):
        await update.message.reply_text("ما عندك صلاحية ❌")
        return

    if not context.args:
        await update.message.reply_text("الاستخدام: /deljob <معرف_الموعد>\nاستخدم /listjobs لرؤية المعرّفات.")
        return

    job_id = context.args[0]
    jobs = load_jobs()
    new_jobs = [j for j in jobs if j["id"] != job_id]

    if len(new_jobs) == len(jobs):
        await update.message.reply_text(f"❌ لا يوجد موعد بالمعرف: <code>{h(job_id)}</code>", parse_mode=HTML)
        return

    save_jobs(new_jobs)

    # إلغاء الوظيفة من job_queue
    for job in context.job_queue.get_jobs_by_name(f"job_{job_id}"):
        job.schedule_removal()

    await update.message.reply_text(f"✅ تم حذف الموعد رقم <code>{h(job_id)}</code>", parse_mode=HTML)


async def delday_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /delday <0-6>
    يحذف كل المواعيد الأسبوعية ليوم معين (0=اثنين، 6=أحد).
    """
    user = update.effective_user
    if not has_permission(user.id, "deljob"):
        await update.message.reply_text("ما عندك صلاحية ❌")
        return

    if not context.args:
        await update.message.reply_text("الاستخدام: /delday <0-6>\n0=اثنين، 6=أحد")
        return

    try:
        day = int(context.args[0])
        if not (0 <= day <= 6):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ اليوم يجب أن يكون بين 0 و 6.")
        return

    jobs = load_jobs()
    to_del  = [j for j in jobs if j.get("type") == "weekly" and j.get("day") == day]
    new_jobs = [j for j in jobs if not (j.get("type") == "weekly" and j.get("day") == day)]
    save_jobs(new_jobs)

    for job_entry in to_del:
        for job in context.job_queue.get_jobs_by_name(f"job_{job_entry['id']}"):
            job.schedule_removal()

    await update.message.reply_text(
        f"✅ تم حذف <b>{len(to_del)}</b> موعد ليوم <b>{DAY_NAMES[day]}</b>",
        parse_mode=HTML
    )


async def listjobs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /listjobs
    يعرض كل المواعيد النشطة.
    """
    user = update.effective_user
    if not has_permission(user.id, "viewjobs"):
        await update.message.reply_text("ما عندك صلاحية ❌")
        return

    jobs = load_jobs()
    daily = load_daily()

    if not jobs and not daily:
        await update.message.reply_text("📭 لا توجد مواعيد مجدولة.")
        return

    lines = ["⏰ <b>المواعيد النشطة:</b>\n"]

    if daily:
        lines.append(
            f"🌅 <b>يومي</b> — {daily['time']} (كل يوم)\n"
            f"   📝 {h(daily['text'][:60])}{'…' if len(daily['text']) > 60 else ''}\n"
        )

    for job in jobs:
        jtype = job.get("type")
        jid   = job.get("id", "؟")
        jtime = job.get("time", "؟")
        jtext = job.get("text", "")

        if jtype == "weekly":
            day_name = DAY_NAMES[int(job.get("day", 0))]
            lines.append(
                f"📅 <b>أسبوعي</b> [<code>{jid}</code>] — {day_name} {jtime}\n"
                f"   📝 {h(jtext[:60])}{'…' if len(jtext) > 60 else ''}"
            )
        elif jtype == "once":
            lines.append(
                f"🗓 <b>مرة واحدة</b> [<code>{jid}</code>] — {job.get('date')} {jtime}\n"
                f"   📝 {h(jtext[:60])}{'…' if len(jtext) > 60 else ''}"
            )

    lines.append("\nللحذف: /deljob <المعرف>")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML)


# ====================================================================
#  معالج الرسائل النصية (إدارة الأدمن + رفع الملفات)
# ====================================================================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    ud      = context.user_data
    action  = ud.get("admin_action")

    # ── إدارة الأدمن: إدخال نص ──
    if action and has_permission(user.id, "admin"):
        text = (update.message.text or "").strip()
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص غير فارغ.")
            return

        conn = get_conn()
        if action == "add_dept":
            conn.execute("INSERT INTO departments (emoji,name,sort_order) VALUES ('🏛',?,?)",
                         (text, 999))
            conn.commit()
            await update.message.reply_text(f"✅ تمت إضافة قسم: <b>{h(text)}</b>",
                                            parse_mode=HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ إدارة الأقسام", callback_data="adm_depts")]]))

        elif action == "edit_dept":
            conn.execute("UPDATE departments SET name=? WHERE id=?", (text, ud["admin_target"]))
            conn.commit()
            await update.message.reply_text(f"✅ تم تعديل اسم القسم إلى: <b>{h(text)}</b>",
                                            parse_mode=HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ إدارة الأقسام", callback_data="adm_depts")]]))

        elif action == "edit_dept_emoji":
            conn.execute("UPDATE departments SET emoji=? WHERE id=?", (text, ud["admin_target"]))
            conn.commit()
            await update.message.reply_text(f"✅ تم تغيير الإيموجي إلى: {h(text)}",
                                            parse_mode=HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ إدارة الأقسام", callback_data="adm_depts")]]))

        elif action == "add_level":
            dept_id = ud["admin_target"]
            conn.execute("INSERT INTO levels (dept_id,name,sort_order) VALUES (?,?,999)", (dept_id, text))
            conn.commit()
            await update.message.reply_text(f"✅ تمت إضافة مستوى: <b>{h(text)}</b>",
                                            parse_mode=HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 إدارة المستويات", callback_data=f"adm_levels_{dept_id}")]]))

        elif action == "edit_level":
            conn.execute("UPDATE levels SET name=? WHERE id=?", (text, ud["admin_target"]))
            conn.commit()
            dept_id = ud.get("admin_dept", 0)
            await update.message.reply_text(f"✅ تم تعديل اسم المستوى إلى: <b>{h(text)}</b>",
                                            parse_mode=HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📚 إدارة المستويات", callback_data=f"adm_levels_{dept_id}")]]))

        elif action == "add_subject":
            level_id = ud["admin_target"]
            dept_id  = ud.get("admin_dept", 0)
            conn.execute("INSERT INTO subjects (level_id,name,sort_order) VALUES (?,?,999)", (level_id, text))
            conn.commit()
            await update.message.reply_text(f"✅ تمت إضافة مادة: <b>{h(text)}</b>",
                                            parse_mode=HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 إدارة المواد", callback_data=f"adm_subjs_{dept_id}_{level_id}")]]))

        elif action == "edit_subject":
            conn.execute("UPDATE subjects SET name=? WHERE id=?", (text, ud["admin_target"]))
            conn.commit()
            dept_id  = ud.get("admin_dept", 0)
            level_id = ud.get("admin_level", 0)
            await update.message.reply_text(f"✅ تم تعديل اسم المادة إلى: <b>{h(text)}</b>",
                                            parse_mode=HTML, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📖 إدارة المواد", callback_data=f"adm_subjs_{dept_id}_{level_id}")]]))

        conn.close()
        ud.pop("admin_action", None)
        return

    # ── رفع ملف من المستخدم ──
    if ud.get("awaiting_file"):
        doc   = update.message.document
        photo = update.message.photo
        if not doc and not photo:
            await update.message.reply_text("❌ يرجى إرسال ملف صالح.")
            return

        for key in ("dept_id", "level_id", "subj_id", "ci"):
            if key not in ud:
                await update.message.reply_text("❌ حدث خطأ، ابدأ من جديد /start")
                ud.clear()
                return

        if doc:
            file_name = doc.file_name or f"file_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            file_id   = doc.file_id
            file_size = doc.file_size or 0
        else:
            file      = photo[-1]
            file_name = f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            file_id   = file.file_id
            file_size = file.file_size or 0

        dept_id  = ud["dept_id"]
        level_id = ud["level_id"]
        subj_id  = ud["subj_id"]
        ci       = ud["ci"]

        conn = get_conn()
        conn.execute(
            "INSERT INTO files (dept_id,level_id,subject_id,cat_idx,file_name,telegram_file_id,file_size,uploaded_by,upload_date) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (dept_id, level_id, subj_id, ci, file_name, file_id, file_size, user.id, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        subj  = db_subject(subj_id)
        sname = subj[1] if subj else "؟"
        cat   = CATEGORIES[ci]
        log_sync(user.id, "upload_file", f"{sname}-{cat}-{file_name}")

        await update.message.reply_text(
            f"✅ <b>تم رفع الملف بنجاح!</b>\n\n"
            f"📄 <code>{h(file_name)}</code>\n"
            f"📏 {round(file_size/1024,1)} KB\n\n"
            f"📂 {h(sname)} ‹ {h(cat)}\n\n"
            "🙏 شكراً على مساهمتك!",
            parse_mode=HTML, reply_markup=main_keyboard(user.id)
        )
        ud.clear()
        return

    # رسالة غير متوقعة
    await update.message.reply_text(
        "اضغط /start للعودة للقائمة الرئيسية."
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"[ERROR] {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ حدث خطأ، يرجى المحاولة مجدداً أو الضغط على /start"
            )
        except Exception:
            pass


# ====================================================================
#  الدالة الرئيسية
# ====================================================================
def main():
    init_database()
    print("✅ قاعدة البيانات جاهزة")

    app = Application.builder().token(TOKEN).build()

    # ── الأوامر الأصلية ──
    app.add_handler(CommandHandler("start", start))

    # ── أوامر إدارة الأدمن ──
    app.add_handler(CommandHandler("addadmin", addadmin_cmd))

    # ── أوامر الرسائل التلقائية ──
    app.add_handler(CommandHandler("addjob",   addjob_cmd))
    app.add_handler(CommandHandler("oncejob",  oncejob_cmd))
    app.add_handler(CommandHandler("setdaily", setdaily_cmd))
    app.add_handler(CommandHandler("deljob",   deljob_cmd))
    app.add_handler(CommandHandler("delday",   delday_cmd))
    app.add_handler(CommandHandler("listjobs", listjobs_cmd))

    # ── المعالجات العامة ──
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    app.add_error_handler(error_handler)

    # ── استعادة الوظائف المجدولة عند التشغيل ──
    restored = restore_jobs(app.job_queue)
    print(f"✅ تم استعادة {restored} وظيفة مجدولة")

    print(f"✅ البوت يعمل | المطور: {DEVELOPER}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
