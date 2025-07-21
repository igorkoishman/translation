import os
import telegram
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler
import boto3
import urllib.request
import uuid

from app2.processor import process_video_for_bot

load_dotenv()
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

# Conversation states
SOURCE_LANG, TARGET_LANG, VIDEO = range(3)
# AWS S3 configuration
# S3_BUCKET = "your-s3-bucket-name"  # Replace with your S3 bucket name
# s3_client = boto3.client("s3")
# Initialize bot
TOKEN = "8170886776:AAFIPACI3c8zyQ442fMkuFBXSisIAXoI1xU"  # Replace with your Telegram bot token

from telegram.ext import CallbackContext



async def start(update, context):
    await update.message.reply_text(
        "Welcome to the Video Translation Bot! Please specify the source language (e.g., 'en' for English)."
    )
    return SOURCE_LANG


async def source_lang(update, context):
    context.user_data["source_lang"] = update.message.text
    await update.message.reply_text(
        "Got it! Now specify the target language (e.g., 'es' for Spanish)."
    )
    return TARGET_LANG


async def target_lang(update, context):
    # Accept comma-separated or space-separated list
    langs = [lang.strip() for lang in update.message.text.replace(',', ' ').split()]
    context.user_data["target_lang"] = langs
    await update.message.reply_text(
        f"Languages set: {', '.join(langs)}. Please upload the video file you want to translate."
    )
    return VIDEO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
async def download_video(context, video, file_name):
    """Download video from Telegram to local storage."""
    file = await context.bot.get_file(video.file_id)
    local_path = f"/tmp/{file_name}"
    local_path2 = BASE_DIR+f"/{file_name}"
    await file.download_to_drive(local_path2)
    return local_path2


# async def upload_to_s3(local_path, file_name):
#     """Upload video to S3 and return the S3 URL."""
#     s3_key = f"videos/{file_name}"
#     try:
#         s3_client.upload_file(local_path, S3_BUCKET, s3_key)
#         return f"https://{S3_BUCKET}.s3.amazonaws.com/{s3_key}"
#     except Exception as e:
#         raise Exception(f"Error uploading to S3: {str(e)}")


async def download_translated_video(translated_url, file_name):
    """Download translated video from the provided URL."""
    translated_file_name = f"/tmp/translated_{file_name}"
    try:
        urllib.request.urlretrieve(translated_url, translated_file_name)
        return translated_file_name
    except Exception as e:
        raise Exception(f"Error downloading translated video: {str(e)}")


async def send_translated_video(update, translated_file_name):
    """Send the translated video back to the user."""
    try:
        await update.message.reply_video(video=open(translated_file_name, "rb"))
        await update.message.reply_text("Translation complete!")
    except Exception as e:
        raise Exception(f"Error sending translated video: {str(e)}")


async def cleanup_files(local_path, translated_file_name):
    """Clean up local files."""
    if os.path.exists(local_path):
        os.remove(local_path)
    if os.path.exists(translated_file_name):
        os.remove(translated_file_name)


# async def video_handler(update, context):
#     print("video_handler triggered!")  # For debug
#     video = update.message.video
#
#     # Accept video files sent as document too
#     if not video and update.message.document:
#         doc = update.message.document
#         if doc.mime_type and doc.mime_type.startswith('video/'):
#             video = doc
#
#     if not video:
#         await update.message.reply_text("Please send a valid video file (as video or as file).")
#         return VIDEO
#
#     print("Received video file_id:", video.file_id)
#     file_name = getattr(video, "file_name", f"{uuid.uuid4()}.mp4")
#     local_path2 = await download_video(context, video, file_name)
#     print("Saved video to", local_path2)
#     MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "models/faster-whisper-small"))
#     # --- Call your processor function here ---
#     try:
#         from processor import process_video_for_bot
#         api_key = os.getenv("GOOGLE_API_KEY")
#         output_languages = [context.user_data["target_lang"]]
#         model_name_or_dir = "models/faster-whisper-model"  # Set to your path
#         results, detected_lang = process_video_for_bot(
#             local_path2,
#             output_languages=output_languages,
#             api_key=api_key,
#             model_name_or_dir=MODEL_PATH,
#             device="cpu"
#         )
#         target_lang = context.user_data["target_lang"]
#         if target_lang in results:
#             translated_file_name = results[target_lang]
#             caption = f"Translated ({target_lang})"
#         else:
#             translated_file_name = results.get('orig')
#             caption = f"Original ({detected_lang})"
#
#         await update.message.reply_text(f"Detected language: {detected_lang}")
#         await update.message.reply_video(video=open(translated_file_name, "rb"), caption=caption)
#         await update.message.reply_text("Done!")
#     except Exception as e:
#         print(f"Error in video_handler: {e}")
#         await update.message.reply_text(str(e))
#         return VIDEO
#     finally:
#         if local_path2 and os.path.exists(local_path2):
#             os.remove(local_path2)
#         if 'translated_file_name' in locals() and translated_file_name and os.path.exists(translated_file_name):
#             os.remove(translated_file_name)
#     return ConversationHandler.END


async def video_handler(update, context):
    print("video_handler triggered!")  # For debug
    video = update.message.video

    if not video and update.message.document:
        doc = update.message.document
        if doc.mime_type and doc.mime_type.startswith('video/'):
            video = doc

    if not video:
        await update.message.reply_text("Please send a valid video file (as video or as file).")
        return VIDEO

    print("Received video file_id:", video.file_id)
    file_name = getattr(video, "file_name", f"{uuid.uuid4()}.mp4")
    local_path2 = await download_video(context, video, file_name)
    print("Saved video to", local_path2)
    MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "models/faster-whisper-small"))
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        # Accept multiple languages
        target_langs = context.user_data["target_lang"]
        output_languages = target_langs if isinstance(target_langs, list) else [target_langs]
        results, detected_lang = process_video_for_bot(
            local_path2,
            output_languages=output_languages,
            api_key=api_key,
            model_name_or_dir=MODEL_PATH,
            device="cpu"
        )

        await update.message.reply_text(f"Detected language: {detected_lang}")
        for lang, translated_file_name in results.items():
            if lang == "orig":
                caption = f"Original ({detected_lang})"
            else:
                caption = f"Translated ({lang})"
            await update.message.reply_video(video=open(translated_file_name, "rb"), caption=caption)
        await update.message.reply_text("Done! All requested videos sent.")
    except Exception as e:
        print(f"Error in video_handler: {e}")
        await update.message.reply_text(str(e))
        return VIDEO
    finally:
        if local_path2 and os.path.exists(local_path2):
            os.remove(local_path2)
        # Optionally clean up all result files
        if 'results' in locals():
            for path in results.values():
                if os.path.exists(path):
                    os.remove(path)
    return ConversationHandler.END


def caption_ai_translate(s3_url: str, source_lang: str, target_lang: str) -> str:
    """
    Placeholder for caption.ai API call to translate video.
    Args:
        s3_url: URL of the video in S3
        source_lang: Source language code
        target_lang: Target language code
    Returns:
        URL of the translated video
    """
    # Implement caption.ai API call here
    pass


async def cancel(update, context):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END
async def debug_all(update, context: CallbackContext):

    print(f"Update received: {update}")



def main():
    # application = Application.builder().token(TOKEN).build()
    # application = Application.builder().token(TOKEN).read_timeout(60).write_timeout(60).connect_timeout(
    #     30).pool_timeout(60).build()
    application = Application.builder().token(TOKEN) \
        .read_timeout(60000) \
        .write_timeout(60000) \
        .connect_timeout(30000) \
        .pool_timeout(60000) \
        .build()
    application.add_handler(MessageHandler(filters.ALL, debug_all), group=1)
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SOURCE_LANG: [MessageHandler(filters.TEXT & ~filters.COMMAND, source_lang)],
            TARGET_LANG: [MessageHandler(filters.TEXT & ~filters.COMMAND, target_lang)],
            VIDEO: [MessageHandler(filters.VIDEO | filters.Document.VIDEO, video_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.run_polling()


if __name__ == "__main__":
    main()