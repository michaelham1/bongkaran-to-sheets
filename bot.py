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
    Application, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
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

# ── Simpan data pending (menunggu konfirmasi button)
# Format: {message_id: {data, row, step, user_id, bot_msg_id}}
pending_data = {}

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

# ── Cek apakah perlu konfirmasi
def perlu_konfirmasi_jumlah(value):
    value_clean = str(value).replace(",", ".").strip()
    bagian_depan = value_clean.split(".")[0]
    return len(bagian_depan) == 3

def perlu_konfirmasi_nominal(value):
    try:
        angka = int(str(value).replace(".", "").replace(",", "").strip())
        return angka < 10000
    except:
        return False

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
        logger.error(f"❌ Gagal format sheet: {e}")

# ── Tambah total + pembatas saat hari berganti
def tambah_total_dan_pembatas(sheet, timestamp_sekarang):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        baris_terakhir = None
        for row in reversed(all_data[1:]):
            if not is_empty(row) and not is_pembatas(row) and not is_total(row):
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

        # Cek apakah total sudah ada
        label_total = format_label_total(dt_terakhir)
        for row in all_data[1:]:
            if is_total(row) and label_total in row[0]:
                return

        # Hitung total
        total_jumlah  = 0.0
        total_nominal = 0
        for row in all_data[1:]:
            if is_empty(row) or is_pembatas(row) or is_total(row):
                continue
            try:
                dt_row = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                if dt_row.date() == dt_terakhir.date():
                    total_jumlah  += parse_jumlah(row[6])
                    total_nominal += parse_rupiah(row[7])
            except:
                continue

        tj_str = str(int(total_jumlah)) if total_jumlah == int(total_jumlah) else str(total_jumlah).replace(".", ",")
        tn_str = "Rp {:,.0f}".format(total_nominal).replace(",", ".")

        sheet.append_row([label_total, "", "", "", "", "", tj_str, tn_str, "", "", ""])
        sheet.append_row([format_label_hari(dt_sekarang)] + [""] * 10)
        format_ulang_sheet(sheet)

        logger.info(f"✅ Total + pembatas ditambahkan: {label_total}")
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

        # Hapus tepat 1 baris kosong
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

        data_rows  = [r for r in new_rows if not is_empty(r) and not is_pembatas(r) and not is_total(r)]
        empty_rows = [r for r in new_rows if is_empty(r)]

        def get_timestamp(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.min

        data_rows.sort(key=get_timestamp)

        def get_date(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").date()
            except:
                return None

        grouped = {}
        for row in data_rows:
            d = get_date(row)
            if d not in grouped:
                grouped[d] = []
            grouped[d].append(row)

        sorted_dates = sorted([d for d in grouped.keys() if d is not None])
        hari_ini     = datetime.now(WIB).date()
        final_rows   = []

        for i, d in enumerate(sorted_dates):
            rows_hari = grouped[d]
            final_rows.extend(rows_hari)

            # Jangan total hari ini
            if d >= hari_ini:
                if i < len(sorted_dates) - 1:
                    dt_next = datetime.combine(sorted_dates[i+1], datetime.min.time())
                    final_rows.append([format_label_hari(dt_next)] + [""] * 10)
                continue

            # Total hari yang sudah selesai
            tj = sum(parse_jumlah(r[6]) for r in rows_hari)
            tn = sum(parse_rupiah(r[7]) for r in rows_hari)
            tj_str = str(int(tj)) if tj == int(tj) else str(tj).replace(".", ",")
            tn_str = "Rp {:,.0f}".format(tn).replace(",", ".")

            dt_hari = datetime.combine(d, datetime.min.time())
            final_rows.append([format_label_total(dt_hari), "", "", "", "", "", tj_str, tn_str, "", "", ""])

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

# ── Simpan data ke sheet
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

# ── Handler pesan masuk
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text      = msg.text
    timestamp = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")
    user_id   = msg.from_user.id
    username  = f"@{msg.from_user.username}" if msg.from_user.username else msg.from_user.first_name

    if ":" not in text:
        return

    data = parse_message(text)

    # ── Validasi semua field
    for validasi, field in [
        (validasi_wa,               data["wa"]),
        (validasi_no_id,            data["no_id"]),
        (validasi_id_penerima,      data["id_penerima"]),
        (validasi_jumlah_bongkaran, data["jumlah_bongkaran"]),
        (validasi_nominal,          data["nominal"]),
    ]:
        if field != "-":
            valid, error_msg = validasi(field)
            if not valid:
                await msg.reply_text(error_msg)
                return

    # ── Format nominal dan jumlah
    nominal_angka  = int(data["nominal"].replace(".", "").replace(",", "").strip()) if data["nominal"] != "-" else 0
    jumlah_raw     = data["jumlah_bongkaran"]

    # ── Tentukan langkah konfirmasi
    butuh_konfirmasi_jumlah  = perlu_konfirmasi_jumlah(jumlah_raw) if jumlah_raw != "-" else False
    butuh_konfirmasi_nominal = perlu_konfirmasi_nominal(data["nominal"]) if data["nominal"] != "-" else False

    if butuh_konfirmasi_jumlah:
        # Simpan ke pending, tanya jumlah dulu
        pending_data[msg.message_id] = {
            "data"          : data,
            "timestamp"     : timestamp,
            "user_id"       : user_id,
            "username"      : username,
            "step"          : "jumlah",
            "orig_msg_id"   : msg.message_id,
            "bot_msg_id"    : None,
        }

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("M", callback_data=f"M|jumlah|{msg.message_id}"),
                InlineKeyboardButton("B", callback_data=f"B|jumlah|{msg.message_id}"),
            ]
        ])

        bot_msg = await msg.reply_text(
            f"❓ {username} Jumlah Bongkaran {jumlah_raw} ini M atau B?",
            reply_markup=keyboard
        )
        pending_data[msg.message_id]["bot_msg_id"] = bot_msg.message_id

    elif butuh_konfirmasi_nominal:
        # Tidak perlu konfirmasi jumlah, langsung tanya nominal
        data["jumlah_bongkaran"] = format_jumlah(jumlah_raw)

        pending_data[msg.message_id] = {
            "data"        : data,
            "timestamp"   : timestamp,
            "user_id"     : user_id,
            "username"    : username,
            "step"        : "nominal",
            "orig_msg_id" : msg.message_id,
            "bot_msg_id"  : None,
        }

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("M", callback_data=f"M|nominal|{msg.message_id}"),
                InlineKeyboardButton("B", callback_data=f"B|nominal|{msg.message_id}"),
            ]
        ])

        nominal_formatted = format_rupiah(data["nominal"])
        bot_msg = await msg.reply_text(
            f"❓ {username} Nominal {nominal_formatted} ini M atau B?",
            reply_markup=keyboard
        )
        pending_data[msg.message_id]["bot_msg_id"] = bot_msg.message_id

    else:
        # Tidak perlu konfirmasi, langsung simpan
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

            # Simpan bot_msg_id untuk fitur hapus
            bot_msg = await msg.reply_text(buat_teks_konfirmasi(data))
            context.bot_data[msg.message_id] = {
                "bot_msg_id" : bot_msg.message_id,
                "timestamp"  : timestamp,
                "user_id"    : user_id,
                "chat_id"    : msg.chat_id,
            }
        except Exception as e:
            logger.error(f"❌ Failed to save: {e}")
            await msg.reply_text("❌ Gagal menyimpan data!")

# ── Handler callback button M / B
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    user_id  = query.from_user.id
    username = f"@{query.from_user.username}" if query.from_user.username else query.from_user.first_name

    parts = query.data.split("|")
    if len(parts) != 3:
        return

    pilihan, step, orig_msg_id = parts[0], parts[1], int(parts[2])

    # Cek apakah data pending ada
    if orig_msg_id not in pending_data:
        await query.answer("⚠️ Data sudah tidak tersedia!", show_alert=True)
        return

    pending = pending_data[orig_msg_id]

    # Cek apakah yang klik adalah pengirim asli
    if user_id != pending["user_id"]:
        await query.answer(
            f"❌ Hanya {pending['username']} yang bisa menjawab ini!",
            show_alert=True
        )
        return

    await query.answer()

    data      = pending["data"]
    timestamp = pending["timestamp"]

    if step == "jumlah":
        if pilihan == "M":
            # Bagi 1000
            jumlah_angka             = float(data["jumlah_bongkaran"].replace(",", "."))
            jumlah_baru              = jumlah_angka / 1000
            data["jumlah_bongkaran"] = format_jumlah(str(jumlah_baru))

            # Format nominal
            data["nominal"] = format_rupiah(data["nominal"]) if data["nominal"] != "-" else "-"

            # Langsung simpan (tidak tanya nominal lagi)
            row = [
                timestamp, data["wa"], data["id_pengirim"],
                data["username_pengirim"], data["no_id"], data["id_penerima"],
                data["jumlah_bongkaran"], data["nominal"], data["bank_ewallet"],
                data["nomor"], data["an"],
            ]

            try:
                sheet = get_sheet()
                simpan_ke_sheet(sheet, row, timestamp)
                logger.info(f"✅ Saved (M) | {data['username_pengirim']}")

                # Edit pesan button jadi konfirmasi
                await query.edit_message_text(buat_teks_konfirmasi(data))
                context.bot_data[orig_msg_id] = {
                    "bot_msg_id" : pending["bot_msg_id"],
                    "timestamp"  : timestamp,
                    "user_id"    : pending["user_id"],
                    "chat_id"    : query.message.chat_id,
                }
            except Exception as e:
                logger.error(f"❌ Failed: {e}")
                await query.edit_message_text("❌ Gagal menyimpan data!")

            del pending_data[orig_msg_id]

        else:  # Pilih B
            # Biarkan jumlah
            data["jumlah_bongkaran"] = format_jumlah(data["jumlah_bongkaran"])

            # Cek apakah nominal perlu konfirmasi
            if perlu_konfirmasi_nominal(data["nominal"]):
                pending["step"] = "nominal"
                nominal_formatted = format_rupiah(data["nominal"])

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("M", callback_data=f"M|nominal|{orig_msg_id}"),
                        InlineKeyboardButton("B", callback_data=f"B|nominal|{orig_msg_id}"),
                    ]
                ])

                await query.edit_message_text(
                    f"❓ {pending['username']} Nominal {nominal_formatted} ini M atau B?",
                    reply_markup=keyboard
                )
            else:
                # Langsung simpan
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
                    logger.info(f"✅ Saved (B) | {data['username_pengirim']}")

                    await query.edit_message_text(buat_teks_konfirmasi(data))
                    context.bot_data[orig_msg_id] = {
                        "bot_msg_id" : pending["bot_msg_id"],
                        "timestamp"  : timestamp,
                        "user_id"    : pending["user_id"],
                        "chat_id"    : query.message.chat_id,
                    }
                except Exception as e:
                    logger.error(f"❌ Failed: {e}")
                    await query.edit_message_text("❌ Gagal menyimpan data!")

                del pending_data[orig_msg_id]

    elif step == "nominal":
        if pilihan == "M":
            # Biarkan nominal
            data["nominal"] = format_rupiah(data["nominal"]) if data["nominal"] != "-" else "-"
        else:  # Pilih B
            # Kalikan 10
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
            logger.info(f"✅ Saved nominal | {data['username_pengirim']}")

            await query.edit_message_text(buat_teks_konfirmasi(data))
            context.bot_data[orig_msg_id] = {
                "bot_msg_id" : pending["bot_msg_id"],
                "timestamp"  : timestamp,
                "user_id"    : pending["user_id"],
                "chat_id"    : query.message.chat_id,
            }
        except Exception as e:
            logger.error(f"❌ Failed: {e}")
            await query.edit_message_text("❌ Gagal menyimpan data!")

        del pending_data[orig_msg_id]

# ── Handler pesan dihapus
async def handle_deleted_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    deleted_msg_id = None

    # Cek apakah ada pesan yang dihapus
    if hasattr(update, 'edited_message') and update.edited_message:
        return

    # Telegram kirim update saat pesan dihapus
    for msg_id, info in list(context.bot_data.items()):
        # Hapus data sheet berdasarkan timestamp
        try:
            sheet    = get_sheet()
            all_data = sheet.get_all_values()
            header   = all_data[0]
            rows     = all_data[1:]

            # Cari baris berdasarkan timestamp
            new_rows  = []
            ditemukan = False
            for row in rows:
                if not is_empty(row) and not is_pembatas(row) and not is_total(row):
                    if row[0] == info["timestamp"]:
                        ditemukan = True
                        continue
                new_rows.append(row)

            if ditemukan:
                # Tulis ulang sheet tanpa baris yang dihapus
                sheet.clear()
                sheet.append_row(header)
                if new_rows:
                    sheet.append_rows(new_rows)

                rapikan_sheet(sheet)
                logger.info(f"✅ Data dihapus dari sheet: {info['timestamp']}")

                # Hapus pesan konfirmasi bot
                try:
                    await context.bot.delete_message(
                        chat_id=info["chat_id"],
                        message_id=info["bot_msg_id"]
                    )
                except:
                    pass

                del context.bot_data[msg_id]

        except Exception as e:
            logger.error(f"❌ Gagal hapus data: {e}")

async def handle_message_deleted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler khusus untuk deteksi pesan dihapus"""
    if not hasattr(update, 'message') or not update.message:
        return

    chat_id = update.message.chat_id
    msg_id  = update.message.message_id
    user_id = update.message.from_user.id if update.message.from_user else None

    # Cek apakah admin
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin = member.status in ["administrator", "creator"]
    except:
        is_admin = False

    # Cari di bot_data
    for orig_id, info in list(context.bot_data.items()):
        if info.get("chat_id") == chat_id:
            # Cek apakah pengirim atau admin
            if user_id == info.get("user_id") or is_admin:
                try:
                    sheet    = get_sheet()
                    all_data = sheet.get_all_values()
                    header   = all_data[0]
                    rows     = all_data[1:]

                    new_rows  = []
                    ditemukan = False
                    for row in rows:
                        if (not is_empty(row) and not is_pembatas(row)
                                and not is_total(row)
                                and row[0] == info["timestamp"]):
                            ditemukan = True
                            continue
                        new_rows.append(row)

                    if ditemukan:
                        sheet.clear()
                        sheet.append_row(header)
                        if new_rows:
                            sheet.append_rows(new_rows)
                        rapikan_sheet(sheet)

                        try:
                            await context.bot.delete_message(
                                chat_id=chat_id,
                                message_id=info["bot_msg_id"]
                            )
                        except:
                            pass

                        del context.bot_data[orig_id]
                        logger.info(f"✅ Data & pesan bot dihapus")
                except Exception as e:
                    logger.error(f"❌ Error hapus: {e}")

# ── Main
def main():
    logger.info("🚀 Bot starting...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.ALL, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("✅ Bot is running. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
