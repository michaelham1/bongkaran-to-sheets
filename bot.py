import logging
import os
import json
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

# ── Format angka dengan titik
def format_jumlah(value):
    try:
        angka = int(value.replace(".", "").replace(",", "").strip())
        return "{:,.0f}".format(angka).replace(",", ".")
    except:
        return value

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
            data["jumlah_bongkaran"] = format_jumlah(value)
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
    wib = pytz.timezone("Asia/Jakarta") timestamp = datetime.now(wib).strftime("%Y-%m-%d %H:%M:%S")

    if ":" in text:
        data = parse_message(text)
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
