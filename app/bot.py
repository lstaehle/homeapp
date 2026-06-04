import os
from telegram.ext import Application, ApplicationBuilder


def build_application() -> Application:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    return ApplicationBuilder().token(token).build()
