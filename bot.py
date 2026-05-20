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

# ── Hari & Bulan Bahasa Indonesia
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

# ── Format label hari
def format_label_hari(dt):
    hari  = HARI[dt.strftime("%A")]
    tgl   = dt.day
    bln   = BULAN[dt.month]
    tahun = dt.year
    return f"═══════ {hari}, {tgl} {bln} {tahun} ═══════"

# ── Format label total
def format_label_total(dt):
    hari  = HARI[dt.strftime("%A")]
    tgl   = dt.day
    bln   = BULAN[dt.month]
    tahun = dt.year
    return f"TOTAL {hari}, {tgl} {bln} {tahun}"

# ── Cek baris pembatas
def is_pembatas(row):
    return any("═══════" in str(cell) for cell in row)

# ── Cek baris total
def is_total(row):
    return any("TOTAL" in str(cell) for cell in row)

# ── Cek baris kosong
def is_empty(row):
    return not any(cell.strip() for cell in row)

# ── Format Rupiah
def format_rupiah(value):
    try:
        angka = int(value.replace(".", "").replace(",", "").strip())
        return "Rp {:,.0f}".format(angka).replace(",", ".")
    except:
        return value

# ── Parse Rupiah ke angka
def parse_rupiah(value):
    try:
        clean = value.replace("Rp", "").replace(".", "").replace(",", "").strip()
        return int(clean)
    except:
        return 0

# ── Format Jumlah Bongkaran
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

# ── Parse Jumlah Bongkaran ke angka
def parse_jumlah(value):
    try:
        return float(value.replace(",", ".").strip())
    except:
        return 0

# ── Validasi Nomor WA
def validasi_wa(value):
    if not re.match(r'^62[\s\d\-]+\d$', value):
        return False, "❌ Format Nomor Whatsapp salah!\nFormat yang benar: 62 8XX-XXXX-XXXX\nTidak boleh ada karakter lain di ujung!"
    return True, ""

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

# ── Validasi Nominal
def validasi_nominal(value):
    try:
        angka = int(value.replace(".", "").replace(",", "").strip())
        if angka < 4000:
            return False, "❌ Nominal minimum Rp 4.000!\nSilakan kirim ulang dengan nominal yang benar."
    except:
        return False, "❌ Nominal hanya boleh angka!\nSilakan kirim ulang dengan format yang benar."
    return True, ""

# ── Format ulang semua pembatas dan total di sheet
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
                    "backgroundColor": {
                        "red": 1.0,
                        "green": 0.95,
                        "blue": 0.4
                    }
                })
    except Exception as e:
        logger.error(f"❌ Gagal format sheet: {e}")

# ── Tambah total + pembatas jika hari berganti
def tambah_total_dan_pembatas(sheet, timestamp_sekarang):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        # Cari baris data terakhir
        baris_terakhir = None
        for row in reversed(all_data[1:]):
            if not is_empty(row) and not is_pembatas(row) and not is_total(row):
                baris_terakhir = row
                break

        if baris_terakhir is None:
            return

        # Ambil tanggal terakhir
        try:
            dt_terakhir = datetime.strptime(baris_terakhir[0], "%Y-%m-%d %H:%M:%S")
        except:
            return

        dt_sekarang = datetime.strptime(timestamp_sekarang, "%Y-%m-%d %H:%M:%S")

        if dt_terakhir.date() >= dt_sekarang.date():
            return

        # Hitung total jumlah bongkaran dan nominal hari terakhir
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

        # Format total jumlah
        if total_jumlah == int(total_jumlah):
            total_jumlah_str = str(int(total_jumlah))
        else:
            total_jumlah_str = str(total_jumlah).replace(".", ",")

        # Format total nominal
        total_nominal_str = "Rp {:,.0f}".format(total_nominal).replace(",", ".")

        # Baris total
        label_total = format_label_total(dt_terakhir)
        baris_total = [label_total, "", "", "", "", "", total_jumlah_str, total_nominal_str, "", "", ""]
        sheet.append_row(baris_total)

        # Baris pembatas hari baru
        label_pembatas = format_label_hari(dt_sekarang)
        baris_pembatas = [label_pembatas] + [""] * 10
        sheet.append_row(baris_pembatas)

        # Format ulang
        format_ulang_sheet(sheet)

        logger.info(f"✅ Total + pembatas ditambahkan!")

    except Exception as e:
        logger.error(f"❌ Gagal tambah total + pembatas: {e}")

# ── Rapikan sheet
def rapikan_sheet(sheet):
    try:
        all_data = sheet.get_all_values()
        if len(all_data) <= 1:
            return

        header = all_data[0]
        rows   = all_data[1:]

        # Hapus tepat 1 baris kosong berturut-turut
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

        # Pisahkan data, pembatas, total, kosong
        data_rows     = [r for r in new_rows if not is_empty(r) and not is_pembatas(r) and not is_total(r)]
        empty_rows    = [r for r in new_rows if is_empty(r)]

        # Sort data berdasarkan timestamp
        def get_timestamp(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            except:
                return datetime.min

        data_rows.sort(key=get_timestamp)

        # Susun ulang dengan total + pembatas di antara hari
        final_rows   = []
        current_date = None
        prev_date    = None

        # Kelompokkan data per hari
        from itertools import groupby
        from datetime import date as date_type

        def get_date(row):
            try:
                return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S").date()
            except:
                return None

        # Grup data per tanggal
        grouped = {}
        for row in data_rows:
            d = get_date(row)
            if d not in grouped:
                grouped[d] = []
            grouped[d].append(row)

        sorted_dates = sorted([d for d in grouped.keys() if d is not None])

        for i, d in enumerate(sorted_dates):
            rows_hari = grouped[d]
            final_rows.extend(rows_hari)

            # Kalau bukan hari terakhir → tambah total
            if i < len(sorted_dates) - 1:
                # Hitung total
                tj = sum(parse_jumlah(r[6]) for r in rows_hari)
                tn = sum(parse_rupiah(r[7]) for r in rows_hari)

                tj_str = str(int(tj)) if tj == int(tj) else str(tj).replace(".", ",")
                tn_str = "Rp {:,.0f}".format(tn).replace(",", ".")

                dt_hari = datetime.combine(d, datetime.min.time())
                label_t = format_label_total(dt_hari)
                final_rows.append([label_t, "", "", "", "", "", tj_str, tn_str, "", "", ""])

                # Tambah pembatas hari berikutnya
                dt_next = datetime.combine(sorted_dates[i+1], datetime.min.time())
                label_p = format_label_hari(dt_next)
                final_rows.append([label_p] + [""] * 10)

        # Tambah baris kosong di akhir
        final_rows += empty_rows

        # Tulis ulang
        sheet.clear()
        sheet.append_row(header)
        if final_rows:
            sheet.append_rows(final_rows)

        # Format ulang
        format_ulang_sheet(sheet)

        logger.info("✅ Sheet berhasil dirapikan!")
    except Exception as e:
        logger.error(f"❌ Gagal rapikan sheet: {e}")

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

# ── Handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    text      = msg.text
    timestamp = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")

    if ":" in text:
        data = parse_message(text)

        # Validasi
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

        # Format
        if data["jumlah_bongkaran"] != "-":
            data["jumlah_bongkaran"] = format_jumlah(data["jumlah_bongkaran"])
        if data["nominal"] != "-":
            data["nominal"] = format_rupiah(data["nominal"])

        row = [
            timestamp, data["wa"], data["id_pengirim"],
            data["username_pengirim"], data["no_id"], data["id_penerima"],
            data["jumlah_bongkaran"], data["nominal"], data["bank_ewallet"],
            data["nomor"], data["an"],
        ]

        try:
            sheet = get_sheet()

            # Tambah total + pembatas jika hari berganti
            tambah_total_dan_pembatas(sheet, timestamp)

            # Simpan data
            sheet.append_row(row)
            logger.info(f"✅ Saved | {data['username_pengirim']} | WA: {data['wa']}")

            # Rapikan
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
