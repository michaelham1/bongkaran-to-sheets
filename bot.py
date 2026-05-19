import logging
import os
import json
import re
from datetime import datetime
import pytz
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

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

# ── Format Rupiah
def format_rupiah(value):
    try:
        angka = int(value.replace(".", "").replace(",", "").strip())
        return "Rp {:,.0f}".format(angka).replace(",", ".")
    except:
        return value

# ── Format Jumlah Bongkaran (support desimal)
def format_jumlah(value):
    try:
        # Ganti koma jadi titik untuk proses
        value_clean = value.replace(",", ".").strip()
        angka = float(value_clean)
        # Kembalikan ke format koma
        if angka == int(angka):
            return str(int(angka))
        else:
            return str(angka).replace(".", ",")
    except:
        return value

# ── Validasi NO ID
def validasi_no_id(value):
    # Hanya boleh angka
    if not value.isdigit():
        return False, "❌ NO ID hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    # Max 3 digit
    if len(value) > 3:
        return False, "❌ NO ID tidak boleh lebih dari 3 digit!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Validasi ID Penerima
def validasi_id_penerima(value):
    # Hanya boleh angka
    if not value.isdigit():
        return False, "❌ ID Penerima hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Validasi Jumlah Bongkaran
def validasi_jumlah_bongkaran(value):
    # Ganti koma jadi titik untuk validasi
    value_clean = value.replace(",", ".").strip()
    # Cek apakah angka valid (boleh desimal)
    try:
        angka = float(value_clean)
    except:
        return False, "❌ Jumlah Bongkaran hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    # Cek max 3 digit (bagian sebelum koma)
    bagian_depan = value_clean.split(".")[0]
    if len(bagian_depan) > 3:
        return False, "❌ Jumlah Bongkaran tidak boleh lebih dari 3 digit!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Rapikan sheet (hapus baris kosong + sort by timestamp)
def rapikan_sheet(sheet):
    try:
        # Ambil semua data
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        header = all_data[0]
        rows   = all_data[1:]

        # Hapus baris kosong
        rows = [row for row in rows if any(cell.strip() for cell in row)]

        # Sort berdasarkan timestamp (kolom pertama = index 0)
        def get_timestamp(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.min

        rows.sort(key=get_timestamp)

        # Tulis ulang ke sheet
        sheet.clear()
        sheet.append_row(header)
        if rows:
            sheet.append_rows(rows)

        logger.info("✅ Sheet berhasil dirapikan!")
    except Exception as e:
        logger.error(f"❌ Gagal rapikan sheet: {e}")

# ── Fungsi pecah pesan berformat
def parse_message(text):
    data = {
        "id_pengirim"      : "-",
        "username_pengirim": "-",
        "no_id"            : "-",
        "id_penerima"      : "-",
        "jumlah_bongkaran" : "-",
        "nominal"          : "-",
        "bank_ewallet"     : "-",
        "nomor"            : "-",
        "an"               : "-",
        "wa"               : "-",
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
            data["nominal"] = format_rupiah(value)
        elif key in ["bank/ewallet", "bank", "ewallet"]:
            data["bank_ewallet"] = value
        elif key == "nomor":
            data["nomor"] = value
        elif key == "an":
            data["an"] = value
        elif key in ["nomor whatsapp", "nomor wahtsapp", "no whatsapp", "wa"]:
            data["wa"] = value

    return data

# ── Handler: setiap pesan masuk
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text      = msg.text
    timestamp = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

    if ":" in text:
        data = parse_message(text)

        # ── Validasi NO ID
        valid, error_msg = validasi_no_id(data["no_id"])
        if not valid:
            await msg.reply_text(error_msg)
            return

        # ── Validasi ID Penerima
        valid, error_msg = validasi_id_penerima(data["id_penerima"])
        if not valid:
            await msg.reply_text(error_msg)
            return

        # ── Validasi Jumlah Bongkaran
        valid, error_msg = validasi_jumlah_bongkaran(data["jumlah_bongkaran"])
        if not valid:
            await msg.reply_text(error_msg)
            return

        # ── Format Jumlah Bongkaran setelah validasi
        data["jumlah_bongkaran"] = format_jumlah(data["jumlah_bongkaran"])

        row = [
            timestamp,
            data["wa"],
            data["id_pengirim"],
            data["username_pengirim"],
            data["no_id"],
            data["id_penerima"],
            data["jumlah_bongkaran"],
            data["nominal"],
            data["bank_ewallet"],
            data["nomor"],
            data["an"],
        ]

        try:
            sheet = get_sheet()
            sheet.append_row(row)
            logger.info(f"✅ Saved | {data['username_pengirim']} | WA: {data['wa']}")

            # ── Rapikan sheet setelah simpan
            rapikan_sheet(sheet)

            await msg.reply_text(
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
        except Exception as e:
            logger.error(f"❌ Failed to save: {e}")
            await msg.reply_text("❌ Gagal menyimpan data!")
    else:
        logger.info("⚠️ Pesan tidak berformat, diabaikan")

# ── Main
def main():
    logger.info("🚀 Bot starting...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, handle_message))
    logger.info("✅ Bot is running. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
