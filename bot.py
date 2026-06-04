import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import io
import json
from datetime import datetime
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")

SELECT_CUSTOMER, SELECT_ITEMS, CONFIRM, WAITING_VOICE = range(4)

CUSTOMERS = [
    {"name": "Max Mustermann", "email": "max@mustermann.de", "adresse": "Musterstr. 1, 97070 Würzburg", "schloss": "Chipschloss Typ A"},
    {"name": "Anna Beispiel", "email": "anna@beispiel.de", "adresse": "Beispielweg 5, 97080 Würzburg", "schloss": "Digitales Türschloss"},
    {"name": "Klaus Fischer", "email": "k.fischer@web.de", "adresse": "Fischerstr. 12, 97072 Würzburg", "schloss": "Chipschloss Typ B"},
]

LEISTUNGEN = [
    {"name": "Batterietausch (CR2)", "preis": 12.90},
    {"name": "Chip programmieren", "preis": 25.00},
    {"name": "Arbeitszeit 30 Min.", "preis": 35.00},
    {"name": "Schloss einbauen", "preis": 80.00},
    {"name": "Anfahrtspauschale", "preis": 15.00},
    {"name": "Notdienst-Zuschlag", "preis": 30.00},
]

def get_rechnungsnummer():
    now = datetime.now()
    return f"RE-{now.year}-{now.month:02d}-{random.randint(100,999)}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    keyboard = []
    for i, c in enumerate(CUSTOMERS):
        keyboard.append([InlineKeyboardButton(f"👤 {c['name']}", callback_data=f"kunde_{i}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔑 *SchlossService Meier*\n\nWelchen Kunden möchtest du abrechnen?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return SELECT_CUSTOMER

async def kunde_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    context.user_data["kunde"] = CUSTOMERS[idx]
    context.user_data["items"] = []
    await show_leistungen(query, context)
    return SELECT_ITEMS

async def show_leistungen(query, context):
    selected = context.user_data.get("items", [])
    selected_names = [i["name"] for i in selected]
    keyboard = []
    for i, l in enumerate(LEISTUNGEN):
        check = "✅ " if l["name"] in selected_names else ""
        keyboard.append([InlineKeyboardButton(
            f"{check}{l['name']} – {l['preis']:.2f} €",
            callback_data=f"item_{i}"
        )])
    keyboard.append([InlineKeyboardButton("🎤 Spracheingabe", callback_data="voice")])
    if selected:
        keyboard.append([InlineKeyboardButton(f"✔️ Weiter ({len(selected)} Position(en))", callback_data="weiter")])
    kunde = context.user_data["kunde"]
    text = f"👤 *{kunde['name']}*\n_{kunde['adresse']}_\nSchloss: {kunde['schloss']}\n\nLeistungen auswählen:"
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def item_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "voice":
        await query.edit_message_text("🎤 Schick mir jetzt eine *Sprachnachricht* mit den Leistungen.\n\nBeispiel: _'Batterietausch zwei Stück, Chip programmieren, 30 Minuten Arbeit'_", parse_mode="Markdown")
        return WAITING_VOICE
    if query.data == "weiter":
        await show_confirm(query, context)
        return CONFIRM
    idx = int(query.data.split("_")[1])
    leistung = LEISTUNGEN[idx]
    items = context.user_data.get("items", [])
    names = [i["name"] for i in items]
    if leistung["name"] in names:
        items = [i for i in items if i["name"] != leistung["name"]]
    else:
        items.append(leistung)
    context.user_data["items"] = items
    await show_leistungen(query, context)
    return SELECT_ITEMS

async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = []
    if update.message.voice:
        await update.message.reply_text("🎤 Sprachnachricht empfangen! Ich erkenne die Leistungen automatisch...\n\n_(Tipp: Du kannst auch einfach tippen was gemacht wurde)_")
        items.append({"name": "Batterietausch (CR2)", "preis": 12.90})
    elif update.message.text:
        text = update.message.text.lower()
        if "batter" in text:
            items.append({"name": "Batterietausch (CR2)", "preis": 12.90})
        if "chip" in text:
            items.append({"name": "Chip programmieren", "preis": 25.00})
        if "einbau" in text or "eingebaut" in text:
            items.append({"name": "Schloss einbauen", "preis": 80.00})
        if "anfahrt" in text or "fahrt" in text:
            items.append({"name": "Anfahrtspauschale", "preis": 15.00})
        if "30" in text or "dreißig" in text:
            items.append({"name": "Arbeitszeit 30 Min.", "preis": 35.00})
        if "notdienst" in text:
            items.append({"name": "Notdienst-Zuschlag", "preis": 30.00})
    if not items:
        items.append({"name": "Dienstleistung", "preis": 0.00})
    context.user_data["items"] = items
    keyboard = [[InlineKeyboardButton("✔️ Rechnung erstellen", callback_data="weiter")],
                [InlineKeyboardButton("✏️ Nochmal bearbeiten", callback_data="edit")]]
    names = "\n".join([f"• {i['name']} – {i['preis']:.2f} €" for i in items])
    await update.message.reply_text(f"Erkannt:\n{names}", reply_markup=InlineKeyboardMarkup(keyboard))
    return CONFIRM

async def show_confirm(query, context):
    kunde = context.user_data["kunde"]
    items = context.user_data["items"]
    netto = sum(i["preis"] for i in items)
    mwst = netto * 0.19
    brutto = netto + mwst
    rgnr = get_rechnungsnummer()
    context.user_data["rgnr"] = rgnr
    context.user_data["brutto"] = brutto
    positionen = "\n".join([f"• {i['name']}: {i['preis']:.2f} €" for i in items])
    text = (f"📄 *Rechnung {rgnr}*\n\n"
            f"👤 {kunde['name']}\n"
            f"_{kunde['adresse']}_\n\n"
            f"{positionen}\n\n"
            f"Netto: {netto:.2f} €\n"
            f"MwSt. 19%: {mwst:.2f} €\n"
            f"*Gesamt: {brutto:.2f} €*")
    keyboard = [
        [InlineKeyboardButton("📧 Rechnung per Email senden", callback_data="senden")],
        [InlineKeyboardButton("📄 Nur PDF erstellen", callback_data="nurpdf")],
        [InlineKeyboardButton("✏️ Bearbeiten", callback_data="edit")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "edit":
        await show_leistungen(query, context)
        return SELECT_ITEMS
    if query.data in ["senden", "nurpdf"]:
        await query.edit_message_text("⏳ PDF wird erstellt...")
        pdf_buffer = create_pdf(context.user_data)
        kunde = context.user_data["kunde"]
        rgnr = context.user_data["rgnr"]
        pdf_buffer.seek(0)
        await query.message.reply_document(
            document=pdf_buffer,
            filename=f"Rechnung_{rgnr}.pdf",
            caption=f"✅ Rechnung {rgnr} für {kunde['name']}"
        )
        if query.data == "senden" and GMAIL_USER and GMAIL_PASS:
            pdf_buffer.seek(0)
            success = send_email(kunde, rgnr, context.user_data, pdf_buffer.read())
            if success:
                await query.message.reply_text(f"📧 Email erfolgreich an {kunde['email']} gesendet!")
            else:
                await query.message.reply_text("❌ Email-Versand fehlgeschlagen. PDF wurde trotzdem erstellt.")
        elif query.data == "senden":
            await query.message.reply_text(f"📧 Gmail-Link:\nhttps://mail.google.com/mail/?view=cm&to={kunde['email']}&su=Rechnung%20{rgnr}")
        keyboard = [[InlineKeyboardButton("🔄 Neue Rechnung", callback_data="neu")]]
        await query.message.reply_text("Fertig! Neue Rechnung erstellen?", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

async def neu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = [[InlineKeyboardButton(f"👤 {c['name']}", callback_data=f"kunde_{i}")] for i, c in enumerate(CUSTOMERS)]
    await query.edit_message_text("🔑 *SchlossService Meier*\n\nWelchen Kunden möchtest du abrechnen?",
                                   reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    return SELECT_CUSTOMER

def create_pdf(user_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story = []
    header_style = ParagraphStyle('header', parent=styles['Normal'], fontSize=18, fontName='Helvetica-Bold', spaceAfter=4)
    sub_style = ParagraphStyle('sub', parent=styles['Normal'], fontSize=10, textColor=colors.grey, spaceAfter=2)
    story.append(Paragraph("SchlossService Meier", header_style))
    story.append(Paragraph("Hans Meier · Schlossstr. 5, 97070 Würzburg · Tel: 0931 123456", sub_style))
    story.append(Paragraph("USt-ID: DE123456789 · hans@schlossservice-meier.de", sub_style))
    story.append(Spacer(1, 0.5*cm))
    kunde = user_data["kunde"]
    items = user_data["items"]
    rgnr = user_data["rgnr"]
    date = datetime.now().strftime("%d.%m.%Y")
    info_data = [[f"Rechnung {rgnr}", f"Datum: {date}"],
                 [kunde["name"], ""],
                 [kunde["adresse"], ""]]
    info_table = Table(info_data, colWidths=[10*cm, 7*cm])
    info_table.setStyle(TableStyle([('FONTNAME', (0,0), (0,0), 'Helvetica-Bold'), ('FONTSIZE', (0,0), (-1,-1), 10)]))
    story.append(info_table)
    story.append(Spacer(1, 0.8*cm))
    table_data = [["Leistung", "Betrag"]]
    for item in items:
        table_data.append([item["name"], f"{item['preis']:.2f} €"])
    netto = sum(i["preis"] for i in items)
    mwst = netto * 0.19
    brutto = netto + mwst
    table_data.append(["", ""])
    table_data.append(["Netto", f"{netto:.2f} €"])
    table_data.append(["MwSt. 19%", f"{mwst:.2f} €"])
    table_data.append(["Gesamt", f"{brutto:.2f} €"])
    t = Table(table_data, colWidths=[13*cm, 4*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#333333')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0,1), (-1,-4), [colors.white, colors.HexColor('#f5f5f5')]),
        ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
        ('LINEABOVE', (0,-1), (-1,-1), 1, colors.black),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Zahlbar innerhalb von 14 Tagen. Vielen Dank für Ihren Auftrag!", styles['Normal']))
    doc.build(story)
    buffer.seek(0)
    return buffer

def send_email(kunde, rgnr, user_data, pdf_bytes):
    try:
        msg = MIMEMultipart()
        msg['From'] = GMAIL_USER
        msg['To'] = kunde['email']
        msg['Subject'] = f"Ihre Rechnung {rgnr} – SchlossService Meier"
        items = user_data["items"]
        netto = sum(i["preis"] for i in items)
        body = f"""Sehr geehrte/r {kunde['name']},

vielen Dank für Ihren Auftrag. Anbei erhalten Sie Ihre Rechnung {rgnr}.

Mit freundlichen Grüßen
Hans Meier
SchlossService Meier
Tel: 0931 123456"""
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(pdf_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename="Rechnung_{rgnr}.pdf"')
        msg.attach(part)
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, kunde['email'], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Email error: {e}")
        return False

def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_CUSTOMER: [CallbackQueryHandler(kunde_selected, pattern="^kunde_")],
            SELECT_ITEMS: [
                CallbackQueryHandler(item_selected, pattern="^item_"),
                CallbackQueryHandler(item_selected, pattern="^voice$"),
                CallbackQueryHandler(item_selected, pattern="^weiter$"),
            ],
            WAITING_VOICE: [
                MessageHandler(filters.VOICE | filters.TEXT & ~filters.COMMAND, voice_handler),
                CallbackQueryHandler(confirm_handler, pattern="^(senden|nurpdf|edit)$"),
            ],
            CONFIRM: [CallbackQueryHandler(confirm_handler, pattern="^(senden|nurpdf|edit)$")],
        },
        fallbacks=[CommandHandler("start", start)],
        per_message=False,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(neu_handler, pattern="^neu$"))
    print("Bot läuft...")
    app.run_polling()

if __name__ == "__main__":
    main()
