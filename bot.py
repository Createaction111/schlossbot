import os
import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
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
    c.drawString(13*cm, height - 3*cm, f"Rechnungs-Nr.: {rechnungsnummer}")
    c.drawString(13*cm, height - 3.5*cm, f"Datum: {datetime.now().strftime('%d.%m.%Y')}")

    c.setFont("Helvetica-Bold", 11)
    c.drawString(2*cm, height - 6*cm, "Rechnungsempfaenger:")
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, height - 6.5*cm, kunde["name"])
    c.drawString(2*cm, height - 7*cm, kunde["adresse"])
    c.drawString(2*cm, height - 7.5*cm, f"Schlosstyp: {kunde.get('schloss', '-')}")

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
        c.drawRightString(19*cm, y, f"{preis:.2f} EUR")
        gesamt += preis

    y -= 0.5*cm
    c.line(2*cm, y, 19*cm, y)
    y -= 0.7*cm
    mwst = gesamt * 0.19
    netto = gesamt - mwst
    c.setFont("Helvetica", 10)
    c.drawString(13*cm, y, "Netto:")
    c.drawRightString(19*cm, y, f"{netto:.2f} EUR")
    y -= 0.5*cm
    c.drawString(13*cm, y, "MwSt. 19%:")
    c.drawRightString(19*cm, y, f"{mwst:.2f} EUR")
    y -= 0.5*cm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(13*cm, y, "GESAMT:")
    c.drawRightString(19*cm, y, f"{gesamt:.2f} EUR")
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
    msg['Subject'] = f"Rechnung Nr. {rechnungsnummer} - SchlossTechnik Meier"
    body = f"Sehr geehrte/r {kunde['name']},\n\nanbei Ihre Rechnung Nr. {rechnungsnummer}.\n\nMit freundlichen Gruessen\nSchlossTechnik Meier"
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(pdf_buffer.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f'attachment; filename="Rechnung_{rechnungsnummer}.pdf"')
    msg.attach(part)
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, kunde["email"], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Email Fehler: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    for i, kunde in enumerate(KUNDEN):
        keyboard.append([InlineKeyboardButton(
            f"👤 {kunde['name']} – {kunde['schloss']}",
            callback_data=f"kunde_{i}"
        )])
    await update.message.reply_text(
        "🔑 *SchlossBot*\n\nWelchen Kunden abrechnen?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def kunde_ausgewaehlt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    kunde = KUNDEN[idx]
    context.user_data['kunde'] = kunde
    context.user_data['leistungen'] = []

    keyboard = []
    row = []
    for name, preis in LEISTUNGEN.items():
        row.append(InlineKeyboardButton(f"{name} ({preis:.0f}€)", callback_data=f"add_{name}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✅ Rechnung erstellen", callback_data="erstellen")])

    await query.edit_message_text(
        f"*Kunde:* {kunde['name']}\n*Schloss:* {kunde['schloss']}\n\nLeistungen antippen (mehrfach = mehrmals):",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


async def leistung_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if query.data.startswith("add_"):
        leistung_name = query.data[4:]
        if 'leistungen' not in context.user_data:
            context.user_data['leistungen'] = []
        context.user_data['leistungen'].append(leistung_name)
        count = context.user_data['leistungen'].count(leistung_name)
        await query.answer(f"✅ {leistung_name} x{count}")

    elif query.data == "erstellen":
        await query.answer()
        leistungen = context.user_data.get('leistungen', [])
        if not leistungen:
            await query.answer("Bitte zuerst Leistungen auswaehlen!", show_alert=True)
            return
        kunde = context.user_data['kunde']
        zusammengefasst = {}
        for l in leistungen:
            zusammengefasst[l] = zusammengefasst.get(l, 0) + 1
        leistungen_liste = [
            {"name": name, "preis": LEISTUNGEN[name], "menge": menge}
            for name, menge in zusammengefasst.items()
        ]
        gesamt = sum(l["preis"] * l["menge"] for l in leistungen_liste)
        rechnungsnummer = f"RE{datetime.now().strftime('%Y%m%d%H%M')}"
        text = f"📄 *Vorschau*\n\n*Kunde:* {kunde['name']}\n*Email:* {kunde['email']}\n\n*Leistungen:*\n"
        for l in leistungen_liste:
            text += f"  • {l['name']} x{l['menge']} = {l['preis']*l['menge']:.2f}€\n"
        text += f"\n*Gesamt (inkl. MwSt.):* {gesamt:.2f}€"
        context.user_data['leistungen_liste'] = leistungen_liste
        context.user_data['rechnungsnummer'] = rechnungsnummer
        keyboard = [
            [InlineKeyboardButton("📧 PDF senden", callback_data="senden")],
            [InlineKeyboardButton("🔄 Neu starten", callback_data="neustart")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif query.data == "senden":
        await query.answer()
        await query.edit_message_text("⏳ Erstelle PDF...")
        kunde = context.user_data['kunde']
        leistungen_liste = context.user_data['leistungen_liste']
        rechnungsnummer = context.user_data['rechnungsnummer']
        pdf_buffer = erstelle_rechnung_pdf(kunde, leistungen_liste, rechnungsnummer)
        pdf_buffer.seek(0)
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=pdf_buffer,
            filename=f"Rechnung_{rechnungsnummer}.pdf",
            caption=f"📄 Rechnung {rechnungsnummer} fuer {kunde['name']}"
        )
        pdf_buffer.seek(0)
        email_ok = sende_email(kunde, pdf_buffer, rechnungsnummer)
        if email_ok:
            status = f"✅ Email an {kunde['email']} gesendet!"
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
        keyboard = []
        for i, kunde in enumerate(KUNDEN):
            keyboard.append([InlineKeyboardButton(
                f"👤 {kunde['name']} – {kunde['schloss']}",
                callback_data=f"kunde_{i}"
            )])
        await query.edit_message_text(
            "🔑 *SchlossBot*\n\nWelchen Kunden abrechnen?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )


async def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN nicht gesetzt!")
        return
    logger.info("Bot laeuft...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(kunde_ausgewaehlt, pattern=r"^kunde_\d+$"))
    app.add_handler(CallbackQueryHandler(leistung_callback, pattern=r"^(add_|erstellen|senden|neustart)"))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
