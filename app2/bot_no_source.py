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
TARGET_LANG, VIDEO = range(2)
# AWS S3 configuration
# S3_BUCKET = "your-s3-bucket-name"  # Replace with your S3 bucket name
# s3_client = boto3.client("s3")
# Initialize bot
TOKEN = "8170886776:AAFIPACI3c8zyQ442fMkuFBXSisIAXoI1xU"  # Replace with your Telegram bot token

from telegram.ext import CallbackContext

VALID_LANGUAGE_CODES = {
    "en", "es", "fr", "de", "he", "ru", "zh", "ja", "it", "ar", "hi", "tr"}



async def target_lang(update, context):
    user_input = update.message.text.strip()
    if user_input.lower() == "next":
        langs = []
    else:
        # Convert everything to lowercase
        langs = [lang.strip().lower() for lang in user_input.replace(',', ' ').split() if lang.strip()]

    if langs:
        invalid = [lang for lang in langs if lang not in VALID_LANGUAGE_CODES]
        if invalid:
            await update.message.reply_text(
                f"❌ Invalid language code(s): {', '.join(invalid)}\n"
                "Please provide valid ISO codes (e.g. 'es', 'fr', 'de'), or type `next` for original subtitles only.\n"
                "Try again:"
            )
            return TARGET_LANG

    context.user_data["target_lang"] = langs
    if langs:
        await update.message.reply_text(
            f"Languages set: {', '.join(langs)}. Now upload your video file."
        )
    else:
        await update.message.reply_text(
            "No translation requested, will return original subtitles only. Now upload your video file."
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
    video = update.message.video
    if not video and update.message.document:
        doc = update.message.document
        if doc.mime_type and doc.mime_type.startswith('video/'):
            video = doc

    if not video:
        await update.message.reply_text("Please send a valid video file (as video or as file).")
        return VIDEO

    file_name = getattr(video, "file_name", f"{uuid.uuid4()}.mp4")
    local_path = await download_video(context, video, file_name)
    MODEL_PATH = os.getenv("MODEL_PATH", os.path.join(BASE_DIR, "models/faster-whisper-small"))
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        target_langs = context.user_data.get("target_lang", [])
        output_languages = target_langs if target_langs else []

        results, detected_lang = process_video_for_bot(
            local_path,
            output_languages=output_languages,
            api_key=api_key,
            model_name_or_dir=MODEL_PATH,
            device="cpu"
        )

        await update.message.reply_text(f"Detected source language: {detected_lang}")

        # Only send 'orig' if no translations are requested or target is same as detected
        sent = False
        for lang, translated_file_name in results.items():
            if lang == "orig":
                # Only send original if NO translation was requested
                if not output_languages:
                    await update.message.reply_video(
                        video=open(translated_file_name, "rb"),
                        caption=f"Original subtitles ({detected_lang})"
                    )
                    sent = True
            else:
                await update.message.reply_video(
                    video=open(translated_file_name, "rb"),
                    caption=f"Translated subtitles ({lang})"
                )
                sent = True
        if not sent:
            # Fallback: send original if nothing else
            if "orig" in results:
                await update.message.reply_video(video=open(results["orig"], "rb"),
                                                 caption=f"Original subtitles ({detected_lang})")
        await update.message.reply_text("Done!")
    except Exception as e:
        print(f"Error in video_handler: {e}")
        await update.message.reply_text(str(e))
        return VIDEO
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
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
    application = Application.builder().token(TOKEN) \
        .read_timeout(60000) \
        .write_timeout(60000) \
        .connect_timeout(30000) \
        .pool_timeout(60000) \
        .build()
    application.add_handler(MessageHandler(filters.ALL, debug_all), group=1)
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.ALL, ask_for_target_language)
        ],
        states={
            TARGET_LANG: [MessageHandler(filters.TEXT & ~filters.COMMAND, target_lang)],
            VIDEO: [MessageHandler(filters.VIDEO | filters.Document.VIDEO, video_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.run_polling()
async def ask_for_target_language(update, context):
    await update.message.reply_text(
        "Hi! Please specify the target language(s) as ISO codes (e.g., 'es' or 'es,fr'). Then send me your video."
    )
    return TARGET_LANG

if __name__ == "__main__":
    main()