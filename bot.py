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
        value_clean = value.replace(",", ".").strip()
        angka = float(value_clean)
        if angka == int(angka):
            return str(int(angka))
        else:
            return str(angka).replace(".", ",")
    except:
        return value

# ── Validasi NO ID
def validasi_no_id(value):
    if not value.isdigit():
        return False, "❌ NO ID hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    if len(value) > 3:
        return False, "❌ NO ID tidak boleh lebih dari 3 digit!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Validasi ID Penerima
def validasi_id_penerima(value):
    if not value.isdigit():
        return False, "❌ ID Penerima hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Validasi Jumlah Bongkaran
def validasi_jumlah_bongkaran(value):
    value_clean = value.replace(",", ".").strip()
    try:
        float(value_clean)
    except:
        return False, "❌ Jumlah Bongkaran hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    bagian_depan = value_clean.split(".")[0]
    if len(bagian_depan) > 3:
        return False, "❌ Jumlah Bongkaran tidak boleh lebih dari 3 digit!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Rapikan sheet
# Hanya naikan baris jika tepat 1 baris kosong berturut-turut
def rapikan_sheet(sheet):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        header = all_data[0]
        rows   = all_data[1:]

        # Tandai baris kosong
        def is_empty(row):
            return not any(cell.strip() for cell in row)

        # Hitung berapa baris kosong berturut-turut
        new_rows = []
        i = 0
        while i < len(rows):
            if is_empty(rows[i]):
                # Cek apakah ini tepat 1 baris kosong
                # Hitung berapa baris kosong berturut-turut mulai dari i
                kosong_count = 0
                j = i
                while j < len(rows) and is_empty(rows[j]):
                    kosong_count += 1
                    j += 1
                
                if kosong_count == 1:
                    # Tepat 1 baris kosong → skip (naikan baris di bawahnya)
                    i += 1
                else:
                    # 2+ baris kosong → biarkan semua
                    for k in range(kosong_count):
                        new_rows.append(rows[i + k])
                    i += kosong_count
            else:
                new_rows.append(rows[i])
                i += 1

        # Sort berdasarkan timestamp
        def get_timestamp(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.min

        # Pisahkan baris kosong dan tidak kosong
        data_rows  = [r for r in new_rows if not is_empty(r)]
        empty_rows = [r for r in new_rows if is_empty(r)]

        # Sort hanya baris yang ada datanya
        data_rows.sort(key=get_timestamp)

        # Gabungkan kembali
        final_rows = data_rows + empty_rows

        # Tulis ulang ke sheet
        sheet.clear()
        sheet.append_row(header)
        if final_rows:
            sheet.append_rows(final_rows)

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
        if data["no_id"] != "-":
            valid, error_msg = validasi_no_id(data["no_id"])
            if not valid:
                await msg.reply_text(error_msg)
                return

        # ── Validasi ID Penerima
        if data["id_penerima"] != "-":
            valid, error_msg = validasi_id_penerima(data["id_penerima"])
            if not valid:
                await msg.reply_text(error_msg)
                return

        # ── Validasi Jumlah Bongkaran
        if data["jumlah_bongkaran"] != "-":
            valid, error_msg = validasi_jumlah_bongkaran(data["jumlah_bongkaran"])
            if not valid:
                await msg.reply_text(error_msg)
                return

        # ── Format Jumlah Bongkaran setelah validasi
        if data["jumlah_bongkaran"] != "-":
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
