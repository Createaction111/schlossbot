import os
import logging
import asyncio
import io
import json
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, InlineQueryHandler, filters, ContextTypes
)
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

KUNDEN_FILE = "kunden.json"
LOG_FILE = "rechnungslog.json"

LEISTUNGEN = {
    "Batterietausch": 15.00,
    "Chip programmieren": 25.00,
    "Schloss einbauen": 80.00,
    "Anfahrt": 20.00,
    "Diagnose": 30.00,
    "Notdienst": 50.00,
}

STUNDENSATZ = 20.00

STANDARD_KUNDEN = [
    {"name": "Max Mustermann", "email": "max@example.com", "adresse": "Musterstr. 1, 97070 Wuerzburg", "schloss": "Chipschloss XY"},
    {"name": "Anna Schmidt", "email": "anna@example.com", "adresse": "Hauptstr. 5, 97080 Wuerzburg", "schloss": "Elektronisches Schloss"},
    {"name": "Klaus Weber", "email": "klaus@example.com", "adresse": "Gartenweg 3, 97082 Wuerzburg", "schloss": "Chipschloss Pro"},
]


def lade_kunden():
    if os.path.exists(KUNDEN_FILE):
        with open(KUNDEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return STANDARD_KUNDEN


def speichere_rechnungslog(eintrag):
    log = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            log = json.load(f)
    log.append(eintrag)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def erstelle_rechnung_pdf(kunde, leistungen, stunden, rechnungsnummer):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 18)
    c.drawString(2*cm, height - 2*cm, "RECHNUNG")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2*cm, height - 3*cm, "SchlossTechnik Meier")
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, height - 3.5*cm, "Schlossweg 1, 97070 Wuerzburg")
    c.drawString(2*cm, height - 4*cm, "Tel: 0931 123456")
    c.drawString(2*cm, height - 4.5*cm, "USt-ID: DE123456789")
    c.drawString(13*cm, height - 3*cm, "Rechnungs-Nr.: " + rechnungsnummer)
    c.drawString(13*cm, height - 3.5*cm, "Datum: " + datetime.now().strftime('%d.%m.%Y'))

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2*cm, height - 6*cm, "Rechnungsempfaenger:")
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, height - 6.5*cm, kunde["name"])
    c.drawString(2*cm, height - 7*cm, kunde["adresse"])
    c.drawString(2*cm, height - 7.5*cm, "Schlosstyp: " + kunde.get("schloss", "-"))

    y = height - 9.5*cm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2*cm, y, "Leistung")
    c.drawString(13*cm, y, "Menge")
    c.drawString(15*cm, y, "Preis")
    y -= 0.3*cm
    c.line(2*cm, y, 19*cm, y)

    gesamt = 0
    c.setFont("Helvetica", 10)
    for leistung in leistungen:
        y -= 0.7*cm
        c.drawString(2*cm, y, leistung["name"])
        c.drawString(13*cm, y, str(leistung.get("menge", 1)))
        preis = leistung["preis"] * leistung.get("menge", 1)
        c.drawRightString(19*cm, y, str(round(preis, 2)) + " EUR")
        gesamt += preis

    if stunden and stunden > 0:
        y -= 0.7*cm
        arbeitspreis = stunden * STUNDENSATZ
        c.drawString(2*cm, y, "Arbeit (" + str(stunden) + " Std. x " + str(STUNDENSATZ) + " EUR/Std.)")
        c.drawString(13*cm, y, "1")
        c.drawRightString(19*cm, y, str(round(arbeitspreis, 2)) + " EUR")
        gesamt += arbeitspreis

    y -= 0.5*cm
    c.line(2*cm, y, 19*cm, y)
    y -= 0.7*cm
    mwst = gesamt * 0.19
    netto = gesamt - mwst
    c.setFont("Helvetica", 10)
    c.drawString(13*cm, y, "Netto:")
    c.drawRightString(19*cm, y, str(round(netto, 2)) + " EUR")
    y -= 0.5*cm
    c.drawString(13*cm, y, "MwSt. 19%:")
    c.drawRightString(19*cm, y, str(round(mwst, 2)) + " EUR")
    y -= 0.5*cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(13*cm, y, "GESAMT:")
    c.drawRightString(19*cm, y, str(round(gesamt, 2)) + " EUR")
    c.setFont("Helvetica", 9)
    c.drawString(2*cm, 2*cm, "Zahlbar innerhalb von 14 Tagen. Vielen Dank!")
    c.save()
    buffer.seek(0)
    return buffer, round(gesamt, 2)


def sende_email(kunde, pdf_buffer, rechnungsnummer):
    if not GMAIL_USER or not GMAIL_PASSWORD:
        return False
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = kunde["email"]
    msg['Subject'] = "Rechnung Nr. " + rechnungsnummer + " - SchlossTechnik Meier"
    body = "Sehr geehrte/r " + kunde["name"] + ",\n\nanbei Ihre Rechnung Nr. " + rechnungsnummer + ".\n\nMit freundlichen Gruessen\nSchlossTechnik Meier"
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(pdf_buffer.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', 'attachment; filename="Rechnung_' + rechnungsnummer + '.pdf"')
    msg.attach(part)
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, kunde["email"], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error("Email Fehler: " + str(e))
        return False


def zeige_leistungen_keyboard():
    keyboard = []
    row = []
    for name, preis in LEISTUNGEN.items():
        row.append(InlineKeyboardButton(name + " (" + str(int(preis)) + "€)", callback_data="add_" + name))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⏱ Arbeitsstunden eingeben", callback_data="stunden")])
    keyboard.append([InlineKeyboardButton("✅ Rechnung erstellen", callback_data="erstellen")])
    return keyboard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔑 SchlossBot\n\n🔍 Kundennamen eingeben (oder Teil davon):\nz.B. 'max' oder 'weber'\n\n📤 Excel hochladen: Schick die Kundenliste als .xlsx Datei"
    )


async def suche_kunde(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Warte auf Stundeneingabe
    if context.user_data.get("warte_auf_stunden"):
        try:
            stunden = float(update.message.text.strip().replace(",", "."))
            context.user_data["stunden"] = stunden
            context.user_data["warte_auf_stunden"] = False
            leistungen = context.user_data.get("leistungen", [])
            stunden_text = " + " + str(stunden) + " Std. Arbeit" if stunden > 0 else ""
            await update.message.reply_text(
                str(len(leistungen)) + " Leistung(en) gewaehlt" + stunden_text + "\n\nWeitere Leistungen oder Rechnung erstellen:",
                reply_markup=InlineKeyboardMarkup(zeige_leistungen_keyboard())
            )
        except ValueError:
            await update.message.reply_text("Bitte eine Zahl eingeben, z.B. 1.5 fuer 1,5 Stunden:")
        return

    text = update.message.text.strip()
    if text.startswith("/"):
        return
    suchbegriff = text.lower()
    kunden = lade_kunden()
    treffer = [(i, k) for i, k in enumerate(kunden) if suchbegriff in k["name"].lower()]
    if not treffer:
        await update.message.reply_text("❌ Kein Kunde gefunden. Nochmal versuchen:")
        return
    keyboard = []
    for i, kunde in treffer:
        keyboard.append([InlineKeyboardButton(
            "👤 " + kunde["name"] + " – " + kunde["schloss"],
            callback_data="kunde_" + str(i)
        )])
    await update.message.reply_text(
        str(len(treffer)) + " Treffer:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def excel_hochladen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.endswith(".xlsx"):
        await update.message.reply_text("Bitte eine .xlsx Datei schicken.")
        return
    await update.message.reply_text("⏳ Lade Excel-Datei...")
    file = await doc.get_file()
    excel_bytes = await file.download_as_bytearray()
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        kunden = []
        headers = [str(ws.cell(1, c).value).strip().lower() for c in range(1, ws.max_column + 1)]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            kunde = {}
            for i, h in enumerate(headers):
                val = str(row[i]).strip() if row[i] is not None else ""
                if "name" in h:
                    kunde["name"] = val
                elif "email" in h or "mail" in h:
                    kunde["email"] = val
                elif "adresse" in h or "adress" in h:
                    kunde["adresse"] = val
                elif "schloss" in h or "typ" in h:
                    kunde["schloss"] = val
            if kunde.get("name"):
                kunden.append(kunde)
        with open(KUNDEN_FILE, "w", encoding="utf-8") as f:
            json.dump(kunden, f, ensure_ascii=False, indent=2)
        await update.message.reply_text(
            "✅ " + str(len(kunden)) + " Kunden geladen!\n\nJetzt Namen eingeben zum Suchen:"
        )
    except Exception as e:
        await update.message.reply_text("❌ Fehler beim Lesen: " + str(e))


async def inline_suche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    kunden = lade_kunden()
    if not query:
        treffer = list(enumerate(kunden))
    else:
        treffer = [(i, k) for i, k in enumerate(kunden) if query in k["name"].lower()]
    results = []
    for i, kunde in treffer[:20]:
        results.append(InlineQueryResultArticle(
            id=str(i),
            title=kunde["name"],
            description=kunde.get("schloss", "") + " | " + kunde.get("adresse", ""),
            input_message_content=InputTextMessageContent("/start_kunde_" + str(i))
        ))
    await update.inline_query.answer(results, cache_time=0)


async def kunde_ausgewaehlt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    kunden = lade_kunden()
    kunde = kunden[idx]
    context.user_data["kunde"] = kunde
    context.user_data["leistungen"] = []
    context.user_data["stunden"] = 0
    await query.edit_message_text(
        "Kunde: " + kunde["name"] + "\nSchloss: " + kunde["schloss"] + "\n\nLeistungen antippen (mehrfach = mehrmals):",
        reply_markup=InlineKeyboardMarkup(zeige_leistungen_keyboard())
    )


async def inline_kunde_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("/start_kunde_"):
        return
    try:
        idx = int(text.replace("/start_kunde_", ""))
        kunden = lade_kunden()
        kunde = kunden[idx]
    except Exception:
        return
    context.user_data["kunde"] = kunde
    context.user_data["leistungen"] = []
    context.user_data["stunden"] = 0
    await update.message.reply_text(
        "Kunde: " + kunde["name"] + "\nSchloss: " + kunde["schloss"] + "\n\nLeistungen antippen:",
        reply_markup=InlineKeyboardMarkup(zeige_leistungen_keyboard())
    )


async def leistung_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data.startswith("add_"):
        leistung_name = query.data[4:]
        if "leistungen" not in context.user_data:
            context.user_data["leistungen"] = []
        context.user_data["leistungen"].append(leistung_name)
        count = context.user_data["leistungen"].count(leistung_name)
        await query.answer(leistung_name + " x" + str(count))

    elif query.data == "stunden":
        await query.answer()
        context.user_data["warte_auf_stunden"] = True
        await query.edit_message_text(
            "Wie viele Arbeitsstunden? (z.B. 1.5 fuer 1,5 Stunden)\n20 EUR pro Stunde\n\nEinfach die Zahl tippen:"
        )

    elif query.data == "erstellen":
        await query.answer()
        leistungen = context.user_data.get("leistungen", [])
        stunden = context.user_data.get("stunden", 0)
        if not leistungen and not stunden:
            await query.answer("Bitte zuerst Leistungen auswaehlen!", show_alert=True)
            return
        kunde = context.user_data["kunde"]
        zusammengefasst = {}
        for l in leistungen:
            zusammengefasst[l] = zusammengefasst.get(l, 0) + 1
        leistungen_liste = [
            {"name": name, "preis": LEISTUNGEN[name], "menge": menge}
            for name, menge in zusammengefasst.items()
        ]
        gesamt = sum(l["preis"] * l["menge"] for l in leistungen_liste)
        if stunden and stunden > 0:
            gesamt += stunden * STUNDENSATZ
        rechnungsnummer = "RE" + datetime.now().strftime('%Y%m%d%H%M')
        text = "Vorschau\n\nKunde: " + kunde["name"] + "\nEmail: " + kunde["email"] + "\n\nLeistungen:\n"
        for l in leistungen_liste:
            text += "  " + l["name"] + " x" + str(l["menge"]) + " = " + str(round(l["preis"]*l["menge"], 2)) + "EUR\n"
        if stunden and stunden > 0:
            text += "  Arbeit " + str(stunden) + " Std. = " + str(round(stunden * STUNDENSATZ, 2)) + "EUR\n"
        text += "\nGesamt (inkl. MwSt.): " + str(round(gesamt, 2)) + "EUR"
        context.user_data["leistungen_liste"] = leistungen_liste
        context.user_data["rechnungsnummer"] = rechnungsnummer
        keyboard = [
            [InlineKeyboardButton("📧 PDF erstellen & senden", callback_data="senden")],
            [InlineKeyboardButton("🔄 Neu starten", callback_data="neustart")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "senden":
        await query.answer()
        await query.edit_message_text("⏳ Erstelle PDF...")
        kunde = context.user_data["kunde"]
        leistungen_liste = context.user_data["leistungen_liste"]
        stunden = context.user_data.get("stunden", 0)
        rechnungsnummer = context.user_data["rechnungsnummer"]

        pdf_buffer, gesamt = erstelle_rechnung_pdf(kunde, leistungen_liste, stunden, rechnungsnummer)
        pdf_buffer.seek(0)
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=pdf_buffer,
            filename="Rechnung_" + rechnungsnummer + ".pdf",
            caption="Rechnung " + rechnungsnummer + " fuer " + kunde["name"]
        )

        # Log speichern
        leistungen_text = ", ".join([l["name"] + " x" + str(l["menge"]) for l in leistungen_liste])
        eintrag = {
            "datum": datetime.now().strftime('%d.%m.%Y %H:%M'),
            "rechnungsnummer": rechnungsnummer,
            "name": kunde["name"],
            "email": kunde["email"],
            "adresse": kunde["adresse"],
            "schloss": kunde.get("schloss", ""),
            "leistungen": leistungen_text,
            "stunden": stunden,
            "gesamt": gesamt
        }
        speichere_rechnungslog(eintrag)

        pdf_buffer.seek(0)
        email_ok = sende_email(kunde, pdf_buffer, rechnungsnummer)
        if email_ok:
            status = "✅ Email an " + kunde["email"] + " gesendet!"
        else:
            status = "✅ PDF erstellt! Email nicht konfiguriert."
        keyboard = [[InlineKeyboardButton("🔄 Neue Rechnung", callback_data="neustart")]]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=status,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "neustart":
        await query.answer()
        context.user_data.clear()
        await query.edit_message_text(
            "🔑 SchlossBot\n\n🔍 Kundennamen eingeben:"
        )


async def log_exportieren(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("Noch keine Rechnungen vorhanden.")
        return
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        log = json.load(f)
    if not log:
        await update.message.reply_text("Log ist leer.")
        return
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Rechnungslog"
        headers = ["Datum", "Rechnungs-Nr.", "Name", "Email", "Adresse", "Schlosstyp", "Leistungen", "Stunden", "Gesamt (EUR)"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", start_color="1F6B3A")
            cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions["A"].width = 18
        ws.column_dimensions["B"].width = 18
        ws.column_dimensions["C"].width = 25
        ws.column_dimensions["D"].width = 30
        ws.column_dimensions["E"].width = 35
        ws.column_dimensions["F"].width = 22
        ws.column_dimensions["G"].width = 40
        ws.column_dimensions["H"].width = 10
        ws.column_dimensions["I"].width = 14
        for eintrag in log:
            ws.append([
                eintrag.get("datum", ""),
                eintrag.get("rechnungsnummer", ""),
                eintrag.get("name", ""),
                eintrag.get("email", ""),
                eintrag.get("adresse", ""),
                eintrag.get("schloss", ""),
                eintrag.get("leistungen", ""),
                eintrag.get("stunden", 0),
                eintrag.get("gesamt", 0),
            ])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=buf,
            filename="Rechnungslog_" + datetime.now().strftime('%Y%m%d') + ".xlsx",
            caption="📊 Rechnungslog mit " + str(len(log)) + " Eintraegen"
        )
    except Exception as e:
        await update.message.reply_text("Fehler beim Export: " + str(e))


async def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN nicht gesetzt!")
        return
    logger.info("Bot laeuft...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("log", log_exportieren))
    app.add_handler(InlineQueryHandler(inline_suche))
    app.add_handler(CallbackQueryHandler(kunde_ausgewaehlt, pattern=r"^kunde_\d+$"))
    app.add_handler(CallbackQueryHandler(leistung_callback, pattern=r"^(add_|stunden|erstellen|senden|neustart)"))
    app.add_handler(MessageHandler(filters.Document.ALL, excel_hochladen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, suche_kunde))
    app.add_handler(MessageHandler(filters.Regex(r"^/start_kunde_"), inline_kunde_start))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
