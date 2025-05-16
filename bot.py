import os
import re
import logging
import random
from time import sleep
from datetime import datetime
from io import BytesIO
from googletrans import Translator, LANGUAGES
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Configuración básica
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class SubtitleTranslator:
    def __init__(self):
        self.translator = Translator()
        self.retry_delay = 5
        self.max_retries = 3
        self.batch_size = 5
        
    async def translate_text(self, text, dest, src='auto'):
        for attempt in range(self.max_retries):
            try:
                result = self.translator.translate(text, dest=dest, src=src)
                return result.text
            except Exception as e:
                logger.warning(f"Intento {attempt+1} fallido: {str(e)}")
                if attempt < self.max_retries - 1:
                    await sleep(self.retry_delay * (attempt + 1))
        return text
    
    def parse_srt(self, file_content):
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
    
    def create_srt(self, subtitles):
        srt_content = []
        for sub in subtitles:
            srt_content.append(f"{sub['index']}\n{sub['start']} --> {sub['end']}\n{sub['text']}\n")
        return BytesIO('\n'.join(srt_content).encode('utf-8'))

    async def translate_srt(self, file_content, dest_lang, src_lang='auto'):
        try:
            subtitles = self.parse_srt(file_content)
            total_subs = len(subtitles)
            translated_subs = []
            
            for i in range(0, total_subs, self.batch_size):
                batch = subtitles[i:i + self.batch_size]
                batch_texts = [sub['text'] for sub in batch]
                
                translated_batch = []
                for text in batch_texts:
                    translated = await self.translate_text(text, dest_lang, src_lang)
                    translated_batch.append(translated)
                    await sleep(random.uniform(0.5, 1.5))
                
                for j, translated_text in enumerate(translated_batch):
                    original_sub = batch[j]
                    translated_subs.append({
                        'index': original_sub['index'],
                        'start': original_sub['start'],
                        'end': original_sub['end'],
                        'text': translated_text
                    })
            
            return self.create_srt(translated_subs)
            
        except Exception as e:
            logger.error(f"Error en traducción: {str(e)}")
            raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
📚 *Bot de Traducción de Subtítulos*

Envía un archivo .srt y elige el idioma de destino.

*Comandos disponibles:*
/start - Muestra este mensaje
/help - Ayuda e instrucciones
/langs - Lista de idiomas soportados
/translate - Inicia el proceso de traducción

Ejemplo: envía un archivo .srt y responde con /translate es
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def list_langs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    langs_text = "🌍 *Idiomas soportados:*\n\n"
    langs_text += "\n".join([f"• {code}: {name}" for code, name in sorted(LANGUAGES.items())])
    await update.message.reply_text(langs_text, parse_mode='Markdown')

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_bytes = BytesIO()
    await file.download_to_memory(file_bytes)
    context.user_data['file'] = file_bytes
    await update.message.reply_text(
        "Archivo recibido. Responde con /translate seguido del código de idioma.\n"
        "Ejemplo: /translate es\n\n"
        "Usa /langs para ver idiomas disponibles."
    )

async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'file' not in context.user_data:
        await update.message.reply_text("Primero envía un archivo .srt")
        return
    
    if not context.args:
        await update.message.reply_text("Debes especificar el idioma destino. Ejemplo: /translate es")
        return
    
    dest_lang = context.args[0].lower()
    if dest_lang not in LANGUAGES:
        await update.message.reply_text(f"Idioma no válido. Usa /langs para ver opciones.")
        return
    
    await update.message.reply_text(f"🚀 Traduciendo al {LANGUAGES[dest_lang]}...")
    
    try:
        translator = SubtitleTranslator()
        file_bytes = context.user_data['file']
        translated_file = await translator.translate_srt(file_bytes.getvalue(), dest_lang)
        
        await update.message.reply_document(
            document=InputFile(translated_file, filename=f"traducido_{dest_lang}.srt"),
            caption=f"✅ Traducción completada a {LANGUAGES[dest_lang]}"
        )
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text("❌ Error al traducir el archivo. Intenta nuevamente.")

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("No se encontró TELEGRAM_BOT_TOKEN en las variables de entorno")
    
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("langs", list_langs))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_document))
    app.add_error_handler(error_handler)
    
    port = int(os.environ.get('PORT', 8443))
    webhook_url = os.getenv('WEBHOOK_URL')
    
    if webhook_url:
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}"
        )
    else:
        app.run_polling()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update.message:
        await update.message.reply_text("❌ Ocurrió un error. Por favor, inténtalo nuevamente.")

if __name__ == '__main__':
    main()
