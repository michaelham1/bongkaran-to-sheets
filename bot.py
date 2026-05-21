import logging
import os
import json
import re
from datetime import datetime
import pytz
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

# ── Load .env
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

# ── Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Timezone WIB
WIB = pytz.timezone("Asia/Jakarta")

# ── Hari & Bulan
HARI = {
    "Monday": "SENIN", "Tuesday": "SELASA", "Wednesday": "RABU",
    "Thursday": "KAMIS", "Friday": "JUMAT", "Saturday": "SABTU",
    "Sunday": "MINGGU"
}
BULAN = {
    1: "JANUARI", 2: "FEBRUARI", 3: "MARET", 4: "APRIL",
    5: "MEI", 6: "JUNI", 7: "JULI", 8: "AGUSTUS",
    9: "SEPTEMBER", 10: "OKTOBER", 11: "NOVEMBER", 12: "DESEMBER"
}

# ── Pending data
pending_data = {}

# ── Simpan mapping pesan → data sheet
saved_messages = {}

# ── Google Sheets Setup
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_sheet():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            "telegram-bot-496706-e8c55e2944e2.json", scopes=SCOPES
        )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet("BONGKARAN")

# ── Format label
def format_label_hari(dt):
    return f"═══════ {HARI[dt.strftime('%A')]}, {dt.day} {BULAN[dt.month]} {dt.year} ═══════"

def format_label_total(dt):
    return f"TOTAL {HARI[dt.strftime('%A')]}, {dt.day} {BULAN[dt.month]} {dt.year}"

# ── Cek tipe baris
def is_pembatas(row):
    return any("═══════" in str(cell) for cell in row)

def is_total(row):
    return any(str(cell).startswith("TOTAL ") for cell in row)

def is_empty(row):
    return not any(cell.strip() for cell in row)

def is_special(row):
    return is_pembatas(row) or is_total(row) or is_empty(row)

# ── Format angka
def format_rupiah(value):
    try:
        angka = int(str(value).replace(".", "").replace(",", "").strip())
        return "Rp {:,.0f}".format(angka).replace(",", ".")
    except:
        return str(value)

def parse_rupiah(value):
    try:
        clean = str(value).replace("Rp", "").replace(".", "").replace(",", "").strip()
        return int(clean)
    except:
        return 0

def format_jumlah(value):
    try:
        value_clean = str(value).replace(",", ".").strip()
        angka = float(value_clean)
        if angka == int(angka):
            return str(int(angka))
        else:
            return str(round(angka, 10)).replace(".", ",")
    except:
        return str(value)

def parse_jumlah(value):
    try:
        return float(str(value).replace(",", ".").strip())
    except:
        return 0

def format_total_jumlah(total):
    if total == int(total):
        return str(int(total))
    return str(round(total, 10)).replace(".", ",")

# ── Cek konfirmasi
def perlu_konfirmasi_jumlah(value):
    value_clean  = str(value).replace(",", ".").strip()
    bagian_depan = value_clean.split(".")[0]
    return len(bagian_depan) == 3

def perlu_konfirmasi_nominal(value):
    try:
        angka = int(str(value).replace(".", "").replace(",", "").strip())
        return angka < 10000
    except:
        return False

# ── Validasi
def validasi_wa(value):
    if not re.match(r'^62[\s\d\-]+\d$', value):
        return False, "❌ Format Nomor Whatsapp salah!\nFormat yang benar: 62 8XX-XXXX-XXXX\nTidak boleh ada karakter lain di ujung!"
    return True, ""

def validasi_no_id(value):
    if not value.isdigit():
        return False, "❌ NO ID hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    if len(value) > 3:
        return False, "❌ NO ID tidak boleh lebih dari 3 digit!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

def validasi_id_penerima(value):
    if not value.isdigit():
        return False, "❌ ID Penerima hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

def validasi_jumlah_bongkaran(value):
    value_clean = str(value).replace(",", ".").strip()
    try:
        float(value_clean)
    except:
        return False, "❌ Jumlah Bongkaran hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    bagian_depan = value_clean.split(".")[0]
    if len(bagian_depan) > 3:
        return False, "❌ Jumlah Bongkaran tidak boleh lebih dari 3 digit!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

def validasi_nominal(value):
    try:
        angka = int(str(value).replace(".", "").replace(",", "").strip())
        if angka < 4000:
            return False, "❌ Nominal minimum Rp 4.000!\nSilakan kirim ulang dengan nominal yang benar."
    except:
        return False, "❌ Nominal hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Format ulang sheet
def format_ulang_sheet(sheet):
    try:
        all_data = sheet.get_all_values()
        for idx, row in enumerate(all_data[1:], start=2):
            if is_pembatas(row):
                sheet.merge_cells(f"A{idx}:K{idx}")
                sheet.format(f"A{idx}:K{idx}", {
                    "horizontalAlignment": "CENTER",
                    "textFormat": {"bold": True}
                })
            elif is_total(row):
                sheet.format(f"A{idx}:K{idx}", {
                    "textFormat": {"bold": True},
                    "backgroundColor": {"red": 1.0, "green": 0.95, "blue": 0.4}
                })
    except Exception as e:
        logger.error(f"❌ Gagal format: {e}")

# ── Hitung total HANYA untuk 1 hari
def hitung_total_satu_hari(all_data, target_date):
    total_jumlah  = 0.0
    total_nominal = 0
    for row in all_data[1:]:
        if is_special(row):
            continue
        try:
            dt_row = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            if dt_row.date() != target_date:
                continue
            total_jumlah  += parse_jumlah(row[6])
            total_nominal += parse_rupiah(row[7])
        except:
            continue
    return total_jumlah, total_nominal

# ── Tambah total + pembatas saat hari berganti
def tambah_total_dan_pembatas(sheet, timestamp_sekarang):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        baris_terakhir = None
        for row in reversed(all_data[1:]):
            if not is_special(row):
                baris_terakhir = row
                break

        if baris_terakhir is None:
            return

        try:
            dt_terakhir = datetime.strptime(baris_terakhir[0], "%Y-%m-%d %H:%M:%S")
        except:
            return

        dt_sekarang = datetime.strptime(timestamp_sekarang, "%Y-%m-%d %H:%M:%S")

        if dt_terakhir.date() >= dt_sekarang.date():
            return

        label_total = format_label_total(dt_terakhir)
        for row in all_data[1:]:
            if is_total(row) and label_total in str(row[0]):
                return

        total_jumlah, total_nominal = hitung_total_satu_hari(
            all_data, dt_terakhir.date()
        )

        tj_str = format_total_jumlah(total_jumlah)
        tn_str = format_rupiah(str(total_nominal))

        sheet.append_row([label_total, "", "", "", "", "", tj_str, tn_str, "", "", ""])
        sheet.append_row([format_label_hari(dt_sekarang)] + [""] * 10)
        format_ulang_sheet(sheet)
        logger.info(f"✅ Total + pembatas: {label_total}")

    except Exception as e:
        logger.error(f"❌ Gagal tambah total: {e}")

# ── Rapikan sheet
def rapikan_sheet(sheet):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        header = all_data[0]
        rows   = all_data[1:]

        new_rows = []
        i = 0
        while i < len(rows):
            if is_empty(rows[i]):
                kosong_count = 0
                j = i
                while j < len(rows) and is_empty(rows[j]):
                    kosong_count += 1
                    j += 1
                if kosong_count == 1:
                    i += 1
                else:
                    for k in range(kosong_count):
                        new_rows.append(rows[i + k])
                    i += kosong_count
            else:
                new_rows.append(rows[i])
                i += 1

        data_rows  = [r for r in new_rows if not is_special(r)]
        empty_rows = [r for r in new_rows if is_empty(r)]

        def get_ts(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.min

        data_rows.sort(key=get_ts)

        grouped = {}
        for row in data_rows:
            try:
                d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").date()
            except:
                d = None
            if d not in grouped:
                grouped[d] = []
            grouped[d].append(row)

        sorted_dates = sorted([d for d in grouped.keys() if d is not None])
        hari_ini     = datetime.now(WIB).date()
        final_rows   = []

        for i, d in enumerate(sorted_dates):
            rows_hari = grouped[d]
            dt_hari   = datetime.combine(d, datetime.min.time())

            final_rows.extend(rows_hari)

            if d < hari_ini:
                tj = sum(parse_jumlah(r[6]) for r in rows_hari)
                tn = sum(parse_rupiah(r[7]) for r in rows_hari)
                tj_str = format_total_jumlah(tj)
                tn_str = format_rupiah(str(tn))
                final_rows.append([
                    format_label_total(dt_hari),
                    "", "", "", "", "", tj_str, tn_str, "", "", ""
                ])
                if i < len(sorted_dates) - 1:
                    dt_next = datetime.combine(sorted_dates[i+1], datetime.min.time())
                    final_rows.append([format_label_hari(dt_next)] + [""] * 10)

        final_rows += empty_rows

        sheet.clear()
        sheet.append_row(header)
        if final_rows:
            sheet.append_rows(final_rows)

        format_ulang_sheet(sheet)
        logger.info("✅ Sheet berhasil dirapikan!")
    except Exception as e:
        logger.error(f"❌ Gagal rapikan: {e}")

# ── Hapus data dari sheet
def hapus_dari_sheet(sheet, timestamp):
    try:
        all_data  = sheet.get_all_values()
        header    = all_data[0]
        rows      = all_data[1:]
        new_rows  = []
        ditemukan = False

        for row in rows:
            if (not is_special(row) and len(row) > 0 and row[0] == timestamp):
                ditemukan = True
                continue
            new_rows.append(row)

        if ditemukan:
            sheet.clear()
            sheet.append_row(header)
            if new_rows:
                sheet.append_rows(new_rows)
            rapikan_sheet(sheet)
            logger.info(f"✅ Data dihapus: {timestamp}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Gagal hapus: {e}")
        return False

# ── Simpan ke sheet
def simpan_ke_sheet(sheet, row, timestamp):
    tambah_total_dan_pembatas(sheet, timestamp)
    sheet.append_row(row)
    rapikan_sheet(sheet)

# ── Parse pesan
def parse_message(text):
    data = {
        "id_pengirim": "-", "username_pengirim": "-",
        "no_id": "-", "id_penerima": "-",
        "jumlah_bongkaran": "-", "nominal": "-",
        "bank_ewallet": "-", "nomor": "-",
        "an": "-", "wa": "-",
    }
    for line in text.strip().split("\n"):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key   = key.strip().lower()
        value = value.strip()
        if key == "id pengirim":
            data["id_pengirim"] = value
        elif key == "username pengirim":
            data["username_pengirim"] = value
        elif key == "no id":
            data["no_id"] = value
        elif key == "id penerima":
            data["id_penerima"] = value
        elif key == "jumlah bongkaran":
            data["jumlah_bongkaran"] = value
        elif key == "nominal":
            data["nominal"] = value
        elif key in ["bank/ewallet", "bank", "ewallet"]:
            data["bank_ewallet"] = value
        elif key == "nomor":
            data["nomor"] = value
        elif key == "an":
            data["an"] = value
        elif key in ["nomor whatsapp", "nomor wahtsapp", "no whatsapp", "wa"]:
            data["wa"] = value
    return data

# ── Keyboard tombol hapus
def buat_keyboard_hapus(orig_msg_id, user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🗑️ Hapus Data",
            callback_data=f"HAPUS|{orig_msg_id}|{user_id}"
        )
    ]])

# ── Keyboard konfirmasi hapus
def buat_keyboard_konfirmasi_hapus(orig_msg_id, user_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "✅ Ya, Hapus",
            callback_data=f"HAPUS_YA|{orig_msg_id}|{user_id}"
        ),
        InlineKeyboardButton(
            "❌ Batal",
            callback_data=f"HAPUS_BATAL|{orig_msg_id}|{user_id}"
        ),
    ]])

# ── Buat teks konfirmasi
def buat_teks_konfirmasi(data):
    return (
        f"✅ Data berhasil dicatat!\n\n"
        f"👤 ID Pengirim   : {data['id_pengirim']}\n"
        f"👤 Username      : {data['username_pengirim']}\n"
        f"🔢 NO ID         : {data['no_id']}\n"
        f"👥 ID Penerima   : {data['id_penerima']}\n"
        f"📦 Jml Bongkaran : {data['jumlah_bongkaran']}\n"
        f"💰 Nominal       : {data['nominal']}\n"
        f"🏦 Bank/Ewallet  : {data['bank_ewallet']}\n"
        f"🔢 Nomor         : {data['nomor']}\n"
        f"👤 AN            : {data['an']}\n"
        f"📱 WA            : {data['wa']}"
    )

# ── Proses pesan (baru dan edited)
async def proses_pesan(msg, context, is_edit=False):
    if not msg or not msg.text:
        return

    user_id  = msg.from_user.id
    username = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.first_name
    chat_id  = msg.chat_id
    text     = msg.text

    if ":" not in text:
        return

    # ── Tentukan timestamp
    if is_edit and msg.message_id in saved_messages:
        old_info  = saved_messages[msg.message_id]
        timestamp = old_info["timestamp"]
        logger.info(f"✅ Edit detected, timestamp lama: {timestamp}")
        try:
            sheet = get_sheet()
            hapus_dari_sheet(sheet, old_info["timestamp"])
            await context.bot.delete_message(
                chat_id=old_info["chat_id"],
                message_id=old_info["bot_msg_id"]
            )
            logger.info(f"✅ Data lama dihapus untuk edit")
        except Exception as e:
            logger.error(f"❌ Gagal hapus data lama: {e}")
        del saved_messages[msg.message_id]
    else:
        timestamp = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

    data = parse_message(text)

    # ── Validasi
    if data["wa"] != "-":
        valid, error_msg = validasi_wa(data["wa"])
        if not valid:
            await msg.reply_text(error_msg)
            return

    if data["no_id"] != "-":
        valid, error_msg = validasi_no_id(data["no_id"])
        if not valid:
            await msg.reply_text(error_msg)
            return

    if data["id_penerima"] != "-":
        valid, error_msg = validasi_id_penerima(data["id_penerima"])
        if not valid:
            await msg.reply_text(error_msg)
            return

    if data["jumlah_bongkaran"] != "-":
        valid, error_msg = validasi_jumlah_bongkaran(data["jumlah_bongkaran"])
        if not valid:
            await msg.reply_text(error_msg)
            return

    if data["nominal"] != "-":
        valid, error_msg = validasi_nominal(data["nominal"])
        if not valid:
            await msg.reply_text(error_msg)
            return

    # ── Cek konfirmasi M/B
    jumlah_raw               = data["jumlah_bongkaran"]
    butuh_konfirmasi_jumlah  = perlu_konfirmasi_jumlah(jumlah_raw) if jumlah_raw != "-" else False
    butuh_konfirmasi_nominal = perlu_konfirmasi_nominal(data["nominal"]) if data["nominal"] != "-" else False

    if butuh_konfirmasi_jumlah:
        pending_data[msg.message_id] = {
            "data"        : data,
            "timestamp"   : timestamp,
            "user_id"     : user_id,
            "username"    : username,
            "step"        : "jumlah",
            "orig_msg_id" : msg.message_id,
            "bot_msg_id"  : None,
            "chat_id"     : chat_id,
        }
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("M", callback_data=f"M|jumlah|{msg.message_id}"),
            InlineKeyboardButton("B", callback_data=f"B|jumlah|{msg.message_id}"),
        ]])
        bot_msg = await msg.reply_text(
            f"❓ {username} Jumlah Bongkaran {jumlah_raw} ini M atau B?",
            reply_markup=keyboard
        )
        pending_data[msg.message_id]["bot_msg_id"] = bot_msg.message_id

    elif butuh_konfirmasi_nominal:
        data["jumlah_bongkaran"] = format_jumlah(jumlah_raw) if jumlah_raw != "-" else "-"
        pending_data[msg.message_id] = {
            "data"        : data,
            "timestamp"   : timestamp,
            "user_id"     : user_id,
            "username"    : username,
            "step"        : "nominal",
            "orig_msg_id" : msg.message_id,
            "bot_msg_id"  : None,
            "chat_id"     : chat_id,
        }
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("M", callback_data=f"M|nominal|{msg.message_id}"),
            InlineKeyboardButton("B", callback_data=f"B|nominal|{msg.message_id}"),
        ]])
        bot_msg = await msg.reply_text(
            f"❓ {username} Nominal {format_rupiah(data['nominal'])} ini M atau B?",
            reply_markup=keyboard
        )
        pending_data[msg.message_id]["bot_msg_id"] = bot_msg.message_id

    else:
        data["jumlah_bongkaran"] = format_jumlah(jumlah_raw) if jumlah_raw != "-" else "-"
        data["nominal"]          = format_rupiah(data["nominal"]) if data["nominal"] != "-" else "-"

        row = [
            timestamp, data["wa"], data["id_pengirim"],
            data["username_pengirim"], data["no_id"], data["id_penerima"],
            data["jumlah_bongkaran"], data["nominal"], data["bank_ewallet"],
            data["nomor"], data["an"],
        ]

        try:
            sheet = get_sheet()
            simpan_ke_sheet(sheet, row, timestamp)
            logger.info(f"✅ Saved | {data['username_pengirim']} | WA: {data['wa']}")

            bot_msg = await msg.reply_text(
                buat_teks_konfirmasi(data),
                reply_markup=buat_keyboard_hapus(msg.message_id, user_id)
            )
            saved_messages[msg.message_id] = {
                "bot_msg_id" : bot_msg.message_id,
                "timestamp"  : timestamp,
                "user_id"    : user_id,
                "chat_id"    : chat_id,
            }
        except Exception as e:
            logger.error(f"❌ Failed: {e}")
            await msg.reply_text("❌ Gagal menyimpan data!")

# ── Handler pesan
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        await proses_pesan(update.edited_message, context, is_edit=True)
    elif update.message:
        await proses_pesan(update.message, context, is_edit=False)

# ── Handler callback
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    await query.answer()

    # ── Tombol HAPUS (tampilkan konfirmasi)
    if query.data.startswith("HAPUS|"):
        parts = query.data.split("|")
        if len(parts) != 3:
            return

        orig_msg_id   = int(parts[1])
        owner_user_id = int(parts[2])

        is_admin = False
        try:
            member   = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in ["administrator", "creator"]
        except:
            pass

        if user_id != owner_user_id and not is_admin:
            await query.answer(
                "❌ Hanya pengirim atau admin yang bisa hapus data ini!",
                show_alert=True
            )
            return

        # Tampilkan konfirmasi hapus
        await query.edit_message_reply_markup(
            reply_markup=buat_keyboard_konfirmasi_hapus(orig_msg_id, owner_user_id)
        )
        return

    # ── Tombol HAPUS_YA (konfirmasi hapus)
    if query.data.startswith("HAPUS_YA|"):
        parts = query.data.split("|")
        if len(parts) != 3:
            return

        orig_msg_id   = int(parts[1])
        owner_user_id = int(parts[2])

        is_admin = False
        try:
            member   = await context.bot.get_chat_member(chat_id, user_id)
            is_admin = member.status in ["administrator", "creator"]
        except:
            pass

        if user_id != owner_user_id and not is_admin:
            await query.answer(
                "❌ Hanya pengirim atau admin yang bisa hapus data ini!",
                show_alert=True
            )
            return

        if orig_msg_id in saved_messages:
            info = saved_messages[orig_msg_id]
            try:
                sheet = get_sheet()
                hapus_dari_sheet(sheet, info["timestamp"])
                await query.edit_message_text("🗑️ Data berhasil dihapus!")
                del saved_messages[orig_msg_id]
                logger.info(f"✅ Data dihapus via tombol")
            except Exception as e:
                logger.error(f"❌ Gagal hapus: {e}")
                await query.edit_message_text("❌ Gagal menghapus data!")
        else:
            await query.edit_message_text("⚠️ Data tidak ditemukan atau sudah dihapus!")
        return

    # ── Tombol HAPUS_BATAL (batalkan hapus)
    if query.data.startswith("HAPUS_BATAL|"):
        parts = query.data.split("|")
        if len(parts) != 3:
            return

        orig_msg_id   = int(parts[1])
        owner_user_id = int(parts[2])

        # Kembalikan ke tombol hapus semula
        if orig_msg_id in saved_messages:
            await query.edit_message_reply_markup(
                reply_markup=buat_keyboard_hapus(orig_msg_id, owner_user_id)
            )
        return

    # ── Handle button M/B
    parts = query.data.split("|")
    if len(parts) != 3:
        return

    pilihan, step, orig_msg_id = parts[0], parts[1], int(parts[2])

    if orig_msg_id not in pending_data:
        await query.answer("⚠️ Data sudah tidak tersedia!", show_alert=True)
        return

    pending = pending_data[orig_msg_id]

    if user_id != pending["user_id"]:
        await query.answer(
            f"❌ Hanya {pending['username']} yang bisa menjawab ini!",
            show_alert=True
        )
        return

    data      = pending["data"]
    timestamp = pending["timestamp"]

    if step == "jumlah":
        if pilihan == "M":
            jumlah_angka             = float(data["jumlah_bongkaran"].replace(",", "."))
            data["jumlah_bongkaran"] = format_jumlah(str(jumlah_angka / 1000))
            data["nominal"]          = format_rupiah(data["nominal"]) if data["nominal"] != "-" else "-"

            row = [
                timestamp, data["wa"], data["id_pengirim"],
                data["username_pengirim"], data["no_id"], data["id_penerima"],
                data["jumlah_bongkaran"], data["nominal"], data["bank_ewallet"],
                data["nomor"], data["an"],
            ]
            try:
                sheet = get_sheet()
                simpan_ke_sheet(sheet, row, timestamp)
                await query.edit_message_text(
                    buat_teks_konfirmasi(data),
                    reply_markup=buat_keyboard_hapus(orig_msg_id, pending["user_id"])
                )
                saved_messages[orig_msg_id] = {
                    "bot_msg_id" : pending["bot_msg_id"],
                    "timestamp"  : timestamp,
                    "user_id"    : pending["user_id"],
                    "chat_id"    : pending["chat_id"],
                }
            except Exception as e:
                logger.error(f"❌ Failed: {e}")
                await query.edit_message_text("❌ Gagal menyimpan data!")
            del pending_data[orig_msg_id]

        else:  # B
            data["jumlah_bongkaran"] = format_jumlah(data["jumlah_bongkaran"])
            if perlu_konfirmasi_nominal(data["nominal"]):
                pending["step"] = "nominal"
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("M", callback_data=f"M|nominal|{orig_msg_id}"),
                    InlineKeyboardButton("B", callback_data=f"B|nominal|{orig_msg_id}"),
                ]])
                await query.edit_message_text(
                    f"❓ {pending['username']} Nominal {format_rupiah(data['nominal'])} ini M atau B?",
                    reply_markup=keyboard
                )
            else:
                data["nominal"] = format_rupiah(data["nominal"]) if data["nominal"] != "-" else "-"
                row = [
                    timestamp, data["wa"], data["id_pengirim"],
                    data["username_pengirim"], data["no_id"], data["id_penerima"],
                    data["jumlah_bongkaran"], data["nominal"], data["bank_ewallet"],
                    data["nomor"], data["an"],
                ]
                try:
                    sheet = get_sheet()
                    simpan_ke_sheet(sheet, row, timestamp)
                    await query.edit_message_text(
                        buat_teks_konfirmasi(data),
                        reply_markup=buat_keyboard_hapus(orig_msg_id, pending["user_id"])
                    )
                    saved_messages[orig_msg_id] = {
                        "bot_msg_id" : pending["bot_msg_id"],
                        "timestamp"  : timestamp,
                        "user_id"    : pending["user_id"],
                        "chat_id"    : pending["chat_id"],
                    }
                except Exception as e:
                    logger.error(f"❌ Failed: {e}")
                    await query.edit_message_text("❌ Gagal menyimpan data!")
                del pending_data[orig_msg_id]

    elif step == "nominal":
        if pilihan == "M":
            data["nominal"] = format_rupiah(data["nominal"]) if data["nominal"] != "-" else "-"
        else:
            nominal_angka   = int(str(data["nominal"]).replace(".", "").replace(",", "").strip())
            data["nominal"] = format_rupiah(str(nominal_angka * 10))

        row = [
            timestamp, data["wa"], data["id_pengirim"],
            data["username_pengirim"], data["no_id"], data["id_penerima"],
            data["jumlah_bongkaran"], data["nominal"], data["bank_ewallet"],
            data["nomor"], data["an"],
        ]
        try:
            sheet = get_sheet()
            simpan_ke_sheet(sheet, row, timestamp)
            await query.edit_message_text(
                buat_teks_konfirmasi(data),
                reply_markup=buat_keyboard_hapus(orig_msg_id, pending["user_id"])
            )
            saved_messages[orig_msg_id] = {
                "bot_msg_id" : pending["bot_msg_id"],
                "timestamp"  : timestamp,
                "user_id"    : pending["user_id"],
                "chat_id"    : pending["chat_id"],
            }
        except Exception as e:
            logger.error(f"❌ Failed: {e}")
            await query.edit_message_text("❌ Gagal menyimpan data!")
        del pending_data[orig_msg_id]

# ── Main
def main():
    logger.info("🚀 Bot starting...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("✅ Bot is running. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
