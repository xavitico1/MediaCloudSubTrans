import os
import re
import logging
import random
from time import sleep
from io import BytesIO
from googletrans import Translator, LANGUAGES
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# Configuración de logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SubtitleTranslator:
    def __init__(self):
        self.translator = Translator()
        self.retry_delay = 2
        self.max_retries = 3
        self.batch_size = 5

    async def translate_text(self, text: str, dest: str, src: str = 'auto') -> str:
        for attempt in range(self.max_retries):
            try:
                result = self.translator.translate(text, dest=dest, src=src)
                return result.text
            except Exception as e:
                logger.warning(f"Intento {attempt + 1} fallido: {str(e)}")
                if attempt < self.max_retries - 1:
                    await sleep(self.retry_delay * (attempt + 1))
        return text

    def parse_srt(self, file_content: bytes) -> list:
        subtitles = []
        pattern = re.compile(
            r'(\d+)\n'
            r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n'
            r'(.+?)(?=\n\n|\Z)',
            re.DOTALL
        )
        
        matches = pattern.finditer(file_content.decode('utf-8-sig'))
        for match in matches:
            subtitles.append({
                'index': match.group(1),
                'start': match.group(2),
                'end': match.group(3),
                'text': match.group(4).replace('\n', ' ')
            })
        return subtitles

    def create_srt(self, subtitles: list) -> BytesIO:
        srt_content = []
        for sub in subtitles:
            srt_content.append(f"{sub['index']}\n{sub['start']} --> {sub['end']}\n{sub['text']}\n")
        return BytesIO('\n'.join(srt_content).encode('utf-8'))

    async def translate_srt(self, file_content: bytes, dest_lang: str, src_lang: str = 'auto') -> BytesIO:
        try:
            subtitles = self.parse_srt(file_content)
            translated_subs = []
            
            for i in range(0, len(subtitles), self.batch_size):
                batch = subtitles[i:i + self.batch_size]
                batch_texts = [sub['text'] for sub in batch]
                
                translated_batch = [
                    await self.translate_text(text, dest_lang, src_lang)
                    for text in batch_texts
                ]
                
                for j, translated_text in enumerate(translated_batch):
                    translated_subs.append({
                        **batch[j],
                        'text': translated_text
                    })
                
                await sleep(random.uniform(0.5, 1.5))  # Pausa anti-bloqueo
            
            return self.create_srt(translated_subs)
            
        except Exception as e:
            logger.error(f"Error en traducción: {str(e)}")
            raise

# Handlers de Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 *Bot de Traducción de Subtítulos*

Envía un archivo .srt y usa /translate [idioma] para traducirlo.

*Comandos:*
/start - Muestra este mensaje
/help - Ayuda
/langs - Lista de idiomas
/translate es - Traducir al español

*Ejemplo:*
1. Envía un archivo .srt
2. Responde con: /translate es
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def list_langs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    langs = "\n".join([f"• {code}: {name}" for code, name in sorted(LANGUAGES.items())])
    await update.message.reply_text(f"🌍 *Idiomas soportados:*\n\n{langs}", parse_mode='Markdown')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_bytes = BytesIO()
    await file.download_to_memory(file_bytes)
    context.user_data['file'] = file_bytes
    await update.message.reply_text(
        "✅ Archivo recibido. Responde con:\n"
        "/translate [idioma]\n\n"
        "Ejemplo: /translate es\n"
        "Ver idiomas: /langs"
    )

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'file' not in context.user_data:
        await update.message.reply_text("⚠️ Primero envía un archivo .srt")
        return
    
    if not context.args:
        await update.message.reply_text("ℹ️ Uso: /translate [idioma]\nEjemplo: /translate es")
        return
    
    dest_lang = context.args[0].lower()
    if dest_lang not in LANGUAGES:
        await update.message.reply_text(f"❌ Idioma no válido. Usa /langs para ver opciones.")
        return
    
    try:
        await update.message.reply_text(f"⏳ Traduciendo al {LANGUAGES[dest_lang]}...")
        translator = SubtitleTranslator()
        file_bytes = context.user_data['file']
        translated_file = await translator.translate_srt(file_bytes.getvalue(), dest_lang)
        
        await update.message.reply_document(
            document=InputFile(translated_file, filename=f"traducido_{dest_lang}.srt"),
            caption=f"✅ Traducción completada a {LANGUAGES[dest_lang]}"
        )
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text("❌ Error al traducir. Intenta nuevamente.")

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("No se configuró TELEGRAM_BOT_TOKEN")
    
    app = Application.builder().token(token).build()
    
    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("langs", list_langs))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_document))
    
    # Configuración para Render
    if os.getenv('RENDER'):
        port = int(os.environ.get('PORT', 8443))
        webhook_url = f"https://{os.getenv('RENDER_SERVICE_NAME')}.onrender.com/{token}"
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=webhook_url
        )
    else:
        app.run_polling()

if __name__ == '__main__':
    main()
