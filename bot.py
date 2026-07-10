import os
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TOKEN = os.getenv("BOT_TOKEN")
TIMEZONE = ZoneInfo("Asia/Hebron")
DATA_FILE = "lessons.json"

NAME, DATE, TIME = range(3)


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def get_user_lessons(user_id):
    data = load_data()
    return data.get(str(user_id), [])


def save_user_lessons(user_id, lessons):
    data = load_data()
    data[str(user_id)] = lessons
    save_data(data)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "مرحبًا بك في بوت تذكير الحصص 📚\n\n"
        "الأوامر المتاحة:\n"
        "/add إضافة حصة\n"
        "/list عرض الحصص\n"
        "/delete حذف حصة\n"
        "/cancel إلغاء العملية"
    )
    await update.message.reply_text(text)


async def add_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اكتب اسم الحصة:")
    return NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["lesson_name"] = update.message.text.strip()
    await update.message.reply_text(
        "اكتب تاريخ الحصة بهذا الشكل:\n"
        "2026-07-15"
    )
    return DATE


async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date_text = update.message.text.strip()

    try:
        lesson_date = datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        await update.message.reply_text(
            "صيغة التاريخ غير صحيحة.\n"
            "اكتبها مثل: 2026-07-15"
        )
        return DATE

    context.user_data["lesson_date"] = date_text
    await update.message.reply_text(
        "اكتب وقت الحصة بنظام 24 ساعة، مثل:\n"
        "14:30"
    )
    return TIME


async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_text = update.message.text.strip()
    date_text = context.user_data["lesson_date"]

    try:
        lesson_datetime = datetime.strptime(
            f"{date_text} {time_text}",
            "%Y-%m-%d %H:%M",
        ).replace(tzinfo=TIMEZONE)
    except ValueError:
        await update.message.reply_text(
            "صيغة الوقت غير صحيحة.\n"
            "اكتبها مثل: 14:30"
        )
        return TIME

    now = datetime.now(TIMEZONE)

    if lesson_datetime <= now:
        await update.message.reply_text(
            "هذا الموعد انتهى أو موجود في الماضي.\n"
            "أدخل موعدًا مستقبليًا."
        )
        return TIME

    lesson_name = context.user_data["lesson_name"]
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    lessons = get_user_lessons(user_id)

    lesson = {
        "name": lesson_name,
        "datetime": lesson_datetime.isoformat(),
        "chat_id": chat_id,
    }

    lessons.append(lesson)
    save_user_lessons(user_id, lessons)

    schedule_notifications(
        context.application,
        user_id,
        lesson,
    )

    day_name = lesson_datetime.strftime("%A")

    await update.message.reply_text(
        "تمت إضافة الحصة ✅\n\n"
        f"اسم الحصة: {lesson_name}\n"
        f"اليوم: {day_name}\n"
        f"التاريخ: {date_text}\n"
        f"الوقت: {time_text}\n\n"
        "سيصلك تذكير قبل يوم، وقبل نصف ساعة، وقبل 15 دقيقة."
    )

    context.user_data.clear()
    return ConversationHandler.END


def schedule_notifications(application, user_id, lesson):
    lesson_datetime = datetime.fromisoformat(
        lesson["datetime"]
    ).astimezone(TIMEZONE)

    reminders = [
      (timedelta(days=1), "بقي يوم واحد على الحصة"),
        (timedelta(minutes=30), "بقي نصف ساعة على الحصة"),
        (timedelta(minutes=15), "بقي 15 دقيقة على الحصة"),
    ]

    now = datetime.now(TIMEZONE)

    for offset, message in reminders:
        reminder_time = lesson_datetime - offset

        if reminder_time > now:
            application.job_queue.run_once(
                send_reminder,
                when=reminder_time,
                data={
                    "chat_id": lesson["chat_id"],
                    "lesson_name": lesson["name"],
                    "lesson_datetime": lesson["datetime"],
                    "message": message,
                },
                name=f"{user_id}_{lesson['datetime']}_{offset}",
            )


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data

    lesson_datetime = datetime.fromisoformat(
        data["lesson_datetime"]
    ).astimezone(TIMEZONE)

    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=(
            f"🔔 تذكير بالحصة\n\n"
            f"{data['message']}\n"
            f"اسم الحصة: {data['lesson_name']}\n"
            f"التاريخ: {lesson_datetime.strftime('%Y-%m-%d')}\n"
            f"الوقت: {lesson_datetime.strftime('%H:%M')}"
        ),
    )


async def list_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lessons = get_user_lessons(user_id)

    if not lessons:
        await update.message.reply_text("لا توجد حصص محفوظة.")
        return

    lessons.sort(key=lambda item: item["datetime"])

    text = "📚 جدول الحصص:\n\n"

    for index, lesson in enumerate(lessons, start=1):
        lesson_datetime = datetime.fromisoformat(
            lesson["datetime"]
        ).astimezone(TIMEZONE)

        text += (
            f"{index}. {lesson['name']}\n"
            f"📅 {lesson_datetime.strftime('%Y-%m-%d')}\n"
            f"⏰ {lesson_datetime.strftime('%H:%M')}\n\n"
        )

    await update.message.reply_text(text)


async def delete_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "اكتب رقم الحصة بعد الأمر.\n"
            "مثال:\n/delete 1\n\n"
            "استخدم /list لمعرفة الأرقام."
        )
        return

    try:
        lesson_number = int(context.args[0]) - 1
    except ValueError:
        await update.message.reply_text("رقم الحصة غير صحيح.")
        return

    user_id = update.effective_user.id
    lessons = get_user_lessons(user_id)

    if lesson_number < 0 or lesson_number >= len(lessons):
        await update.message.reply_text("لا توجد حصة بهذا الرقم.")
        return

    deleted = lessons.pop(lesson_number)
    save_user_lessons(user_id, lessons)

    for job in context.application.job_queue.jobs():
        if (
            str(user_id) in job.name
            and deleted["datetime"] in job.name
        ):
            job.schedule_removal()

    await update.message.reply_text(
        f"تم حذف حصة: {deleted['name']} ✅"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END


def restore_jobs(application):
    data = load_data()
    now = datetime.now(TIMEZONE)

    for user_id, lessons in data.items():
        for lesson in lessons:
            lesson_datetime = datetime.fromisoformat(
                lesson["datetime"]
            ).astimezone(TIMEZONE)

            if lesson_datetime > now:
                schedule_notifications(
                    application,
                    user_id,
                    lesson,
                )


def main():
    if not TOKEN:
        raise ValueError(
            "لم يتم العثور على BOT_TOKEN في متغيرات البيئة."
        )

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    add_conversation = ConversationHandler(
      entry_points=[CommandHandler("add", add_lesson)],
        states={
            NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_name,
                )
            ],
            DATE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_date,
                )
            ],
            TIME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_time,
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_conversation)
    application.add_handler(CommandHandler("list", list_lessons))
    application.add_handler(CommandHandler("delete", delete_lesson))
    application.add_handler(CommandHandler("cancel", cancel))

    application.run_polling()


async def post_init(application):
    restore_jobs(application)


if name == "__main__":
    main()
