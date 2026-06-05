import os
import logging
import asyncio
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
import io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

KUNDEN = [
    {"name": "Max Mustermann", "email": "max@example.com", "adresse": "Musterstr. 1, 97070 Wuerzburg", "schloss": "Chipschloss XY"},
    {"name": "Anna Schmidt", "email": "anna@example.com", "adresse": "Hauptstr. 5, 97080 Wuerzburg", "schloss": "Elektronisches Schloss"},
    {"name": "Klaus Weber", "email": "klaus@example.com", "adresse": "Gartenweg 3, 97082 Wuerzburg", "schloss": "Chipschloss Pro"},
]

LEISTUNGEN = {
    "Batterietausch": 15.00,
    "Chip programmieren": 25.00,
    "Schloss einbauen": 80.00,
    "Anfahrt": 20.00,
    "Diagnose": 30.00,
    "Notdienst": 50.00,
}


def erstelle_rechnung_pdf(kunde, leistungen, rechnungsnummer):
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
    return buffer


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


def zeige_leistungen_keyboard(kunde):
    keyboard = []
    row = []
    for name, preis in LEISTUNGEN.items():
        row.append(InlineKeyboardButton(name + " (" + str(int(preis)) + "€)", callback_data="add_" + name))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✅ Rechnung erstellen", callback_data="erstellen")])
    return keyboard


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔑 SchlossBot\n\n🔍 Tippe einen Kundennamen (oder Teil davon):\nz.B. 'max' oder 'weber'"
    )


async def suche_kunde(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    suchbegriff = text.lower()
    treffer = [(i, k) for i, k in enumerate(KUNDEN) if suchbegriff in k["name"].lower()]
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


async def inline_suche(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip().lower()
    if not query:
        treffer = list(enumerate(KUNDEN))
    else:
        treffer = [(i, k) for i, k in enumerate(KUNDEN) if query in k["name"].lower()]
    results = []
    for i, kunde in treffer:
        results.append(InlineQueryResultArticle(
            id=str(i),
            title=kunde["name"],
            description=kunde["schloss"] + " | " + kunde["adresse"],
            input_message_content=InputTextMessageContent("/start_kunde_" + str(i))
        ))
    await update.inline_query.answer(results, cache_time=0)


async def kunde_ausgewaehlt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    kunde = KUNDEN[idx]
    context.user_data["kunde"] = kunde
    context.user_data["leistungen"] = []
    keyboard = zeige_leistungen_keyboard(kunde)
    await query.edit_message_text(
        "Kunde: " + kunde["name"] + "\nSchloss: " + kunde["schloss"] + "\n\nLeistungen antippen (mehrfach = mehrmals):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def inline_kunde_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("/start_kunde_"):
        return
    try:
        idx = int(text.replace("/start_kunde_", ""))
        kunde = KUNDEN[idx]
    except Exception:
        return
    context.user_data["kunde"] = kunde
    context.user_data["leistungen"] = []
    keyboard = zeige_leistungen_keyboard(kunde)
    await update.message.reply_text(
        "Kunde: " + kunde["name"] + "\nSchloss: " + kunde["schloss"] + "\n\nLeistungen antippen:",
        reply_markup=InlineKeyboardMarkup(keyboard)
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

    elif query.data == "erstellen":
        await query.answer()
        leistungen = context.user_data.get("leistungen", [])
        if not leistungen:
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
        rechnungsnummer = "RE" + datetime.now().strftime('%Y%m%d%H%M')
        text = "Vorschau\n\nKunde: " + kunde["name"] + "\nEmail: " + kunde["email"] + "\n\nLeistungen:\n"
        for l in leistungen_liste:
            text += "  " + l["name"] + " x" + str(l["menge"]) + " = " + str(round(l["preis"]*l["menge"], 2)) + "€\n"
        text += "\nGesamt (inkl. MwSt.): " + str(round(gesamt, 2)) + "€"
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
        rechnungsnummer = context.user_data["rechnungsnummer"]
        pdf_buffer = erstelle_rechnung_pdf(kunde, leistungen_liste, rechnungsnummer)
        pdf_buffer.seek(0)
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=pdf_buffer,
            filename="Rechnung_" + rechnungsnummer + ".pdf",
            caption="Rechnung " + rechnungsnummer + " fuer " + kunde["name"]
        )
        pdf_buffer.seek(0)
        email_ok = sende_email(kunde, pdf_buffer, rechnungsnummer)
        if email_ok:
            status = "✅ Email an " + kunde["email"] + " gesendet!"
        else:
            status = "✅ PDF erstellt! Email nicht konfiguriert – PDF oben weiterleiten."
        keyboard = [[InlineKeyboardButton("🔄 Neue Rechnung", callback_data="neustart")]]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=status,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == "neustart":
        await query.answer()
        await query.edit_message_text(
            "🔑 SchlossBot\n\n🔍 Tippe einen Kundennamen (oder Teil davon):"
        )


async def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN nicht gesetzt!")
        return
    logger.info("Bot laeuft...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(InlineQueryHandler(inline_suche))
    app.add_handler(CallbackQueryHandler(kunde_ausgewaehlt, pattern=r"^kunde_\d+$"))
    app.add_handler(CallbackQueryHandler(leistung_callback, pattern=r"^(add_|erstellen|senden|neustart)"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, suche_kunde))
    app.add_handler(MessageHandler(filters.Regex(r"^/start_kunde_"), inline_kunde_start))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
