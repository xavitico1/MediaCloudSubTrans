import os
import re
import logging
import random
from time import sleep
from io import BytesIO
from google_trans_new import google_translator
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Configuración
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SubtitleTranslator:
    def __init__(self):
        self.translator = google_translator()
        self.retry_delay = 1.5
        self.max_retries = 3
        self.batch_size = 3  # Más pequeño para evitar timeouts

    async def translate_text(self, text: str, dest: str, src: str = 'auto') -> str:
        for attempt in range(self.max_retries):
            try:
                return self.translator.translate(text, lang_tgt=dest, lang_src=src)
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt < self.max_retries - 1:
                    await sleep(self.retry_delay * (attempt + 1))
        return text

    def parse_srt(self, content: bytes) -> list:
        pattern = re.compile(
            r'(\d+)\n'
            r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n'
            r'(.+?)(?=\n\n|\Z)',
            re.DOTALL
        )
        return [
            {
                'index': m.group(1),
                'start': m.group(2),
                'end': m.group(3),
                'text': m.group(4).replace('\n', ' ')
            }
            for m in pattern.finditer(content.decode('utf-8-sig'))
        ]

    def create_srt(self, subs: list) -> BytesIO:
        srt_content = "\n\n".join(
            f"{s['index']}\n{s['start']} --> {s['end']}\n{s['text']}"
            for s in subs
        )
        return BytesIO(srt_content.encode('utf-8'))

    async def translate_srt(self, file_content: bytes, dest_lang: str) -> BytesIO:
        subs = self.parse_srt(file_content)
        translated = []
        
        for i in range(0, len(subs), self.batch_size):
            batch = subs[i:i + self.batch_size]
            texts = [s['text'] for s in batch]
            
            try:
                translated_batch = [
                    await self.translate_text(text, dest_lang)
                    for text in texts
                ]
                
                for j, text in enumerate(translated_batch):
                    translated.append({
                        **batch[j],
                        'text': text
                    })
                
                await sleep(random.uniform(0.3, 1.2))  # Pausa anti-bloqueo
                
            except Exception as e:
                logger.error(f"Batch {i//self.batch_size} failed: {str(e)}")
                raise
        
        return self.create_srt(translated)

# Handlers de Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Envíame un archivo .srt y luego usa /translate <idioma>\n"
        "Ejemplo: /translate es\n\n"
        "Ver idiomas: /langs\n"
        "Ayuda: /help"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Cómo usar:\n"
        "1. Envía archivo .srt\n"
        "2. Responde con: /translate <idioma>\n\n"
        "Ejemplo: /translate fr\n"
        "Idiomas: /langs"
    )

async def list_langs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    langs = "\n".join([
        "• es: Español", "• en: Inglés", "• fr: Francés", 
        "• de: Alemán", "• it: Italiano", "• pt: Portugués",
        "• ru: Ruso", "• ja: Japonés", "• zh-cn: Chino"
    ])
    await update.message.reply_text(f"🌍 Idiomas soportados:\n\n{langs}")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_bytes = BytesIO()
    await file.download_to_memory(file_bytes)
    context.user_data['file'] = file_bytes
    await update.message.reply_text(
        "✅ Archivo recibido. Ahora envía:\n"
        "/translate <idioma>\n\n"
        "Ejemplo: /translate es"
    )

async def translate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'file' not in context.user_data:
        await update.message.reply_text("⚠️ Primero envía un archivo .srt")
        return
    
    if not context.args:
        await update.message.reply_text("ℹ️ Uso: /translate <idioma>\nEjemplo: /translate es")
        return
    
    lang = context.args[0].lower()
    valid_langs = ['es', 'en', 'fr', 'de', 'it', 'pt', 'ru', 'ja', 'zh-cn']
    
    if lang not in valid_langs:
        await update.message.reply_text("❌ Idioma no válido. Usa /langs")
        return
    
    try:
        msg = await update.message.reply_text(f"⏳ Traduciendo al {lang}...")
        translator = SubtitleTranslator()
        translated = await translator.translate_srt(
            context.user_data['file'].getvalue(),
            lang
        )
        await update.message.reply_document(
            InputFile(translated, filename=f"traducido_{lang}.srt"),
            caption=f"✅ Traducido al {lang}"
        )
        await msg.delete()
    except Exception as e:
        logger.error(f"Translation error: {str(e)}")
        await update.message.reply_text("❌ Error al traducir. Intenta nuevamente.")

def main():
    app = Application.builder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("langs", list_langs))
    app.add_handler(CommandHandler("translate", translate_cmd))
    app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_file))
    
    # Webhook para Render
    if os.getenv('RENDER'):
        app.run_webhook(
            listen="0.0.0.0",
            port=int(os.getenv('PORT', 8443)),
            webhook_url=f"{os.getenv('WEBHOOK_URL')}/{os.getenv('TELEGRAM_BOT_TOKEN')}"
        )
    else:
        app.run_polling()

if __name__ == '__main__':
    main()
