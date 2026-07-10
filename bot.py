import json
import logging
import os
from datetime import datetime, time, timedelta
from pathlib import Path
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
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

TOKEN = os.getenv("BOT_TOKEN")
TIMEZONE = ZoneInfo("Asia/Hebron")
DATA_FILE = Path("lessons.json")

ASK_NAME, ASK_DAY, ASK_TIME = range(3)

DAYS = {
    "الأحد": 0,
    "الاحد": 0,
    "الإثنين": 1,
    "الاثنين": 1,
    "الإثنين": 1,
    "الثلاثاء": 2,
    "الأربعاء": 3,
    "الاربعاء": 3,
    "الخميس": 4,
    "الجمعة": 5,
    "السبت": 6,
}

DAY_NAMES = {
    0: "الأحد",
    1: "الإثنين",
    2: "الثلاثاء",
    3: "الأربعاء",
    4: "الخميس",
    5: "الجمعة",
    6: "السبت",
}


def load_lessons():
    if not DATA_FILE.exists():
        return []

    try:
        with DATA_FILE.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return []


def save_lessons(lessons):
    with DATA_FILE.open("w", encoding="utf-8") as file:
        json.dump(lessons, file, ensure_ascii=False, indent=2)


def shifted_schedule(day, hour, minute, minutes_before):
    anchor = datetime(2026, 7, 5, hour, minute)
    lesson_datetime = anchor + timedelta(days=day)
    reminder_datetime = lesson_datetime - timedelta(minutes=minutes_before)

    reminder_day = reminder_datetime.weekday()

    # تحويل ترتيب بايثون: الاثنين=0
    # إلى ترتيب JobQueue: الأحد=0
    reminder_day = (reminder_day + 1) % 7

    return reminder_day, reminder_datetime.time()


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data

    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=(
            "🔔 تذكير بالحصة\n\n"
            f"📚 الحصة: {data['name']}\n"
            f"📅 اليوم: {DAY_NAMES[data['day']]}\n"
            f"⏰ الموعد: {data['time']}\n\n"
            f"{data['message']}"
        ),
    )


def schedule_lesson(application, lesson):
    job_prefix = f"lesson_{lesson['id']}"

    for job in application.job_queue.jobs():
        if job.name and job.name.startswith(job_prefix):
            job.schedule_removal()

    hour, minute = map(int, lesson["time"].split(":"))

    reminders = [
        (1440, "بقي يوم واحد على الحصة."),
        (30, "بقي نصف ساعة على الحصة."),
        (15, "بقي 15 دقيقة على الحصة."),
    ]

    for minutes_before, message in reminders:
        reminder_day, reminder_time = shifted_schedule(
            lesson["day"],
            hour,
            minute,
            minutes_before,
        )

        application.job_queue.run_daily(
            send_reminder,
            time=time(
                reminder_time.hour,
                reminder_time.minute,
                tzinfo=TIMEZONE,
            ),
            days=(reminder_day,),
            data={
                "chat_id": lesson["chat_id"],
                "name": lesson["name"],
                "day": lesson["day"],
                "time": lesson["time"],
                "message": message,
            },
            name=f"{job_prefix}_{minutes_before}",
        )


async def restore_jobs(application):
    for lesson in load_lessons():
        schedule_lesson(application, lesson)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحبًا بك في بوت تذكير الحصص 📚\n\n"
        "الأوامر:\n"
        "/add إضافة حصة أسبوعية\n"
        "/list عرض الحصص\n"
        "/delete حذف حصة\n"
        "/cancel إلغاء العملية"
    )


async def add_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("اكتب اسم الحصة:")
    return ASK_NAME


async def receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["lesson_name"] = update.message.text.strip()

    await update.message.reply_text(
        "اكتب يوم الحصة، مثل:\n"
        "الأحد\n"
        "الإثنين\n"
        "الثلاثاء"
    )

    return ASK_DAY


async def receive_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day_text = update.message.text.strip()

    if day_text not in DAYS:
        await update.message.reply_text(
            "اليوم غير صحيح.\n"
            "اكتب مثلًا: الأحد أو الإثنين أو الثلاثاء"
        )
        return ASK_DAY

    context.user_data["lesson_day"] = DAYS[day_text]

    await update.message.reply_text(
        "اكتب وقت بداية الحصة بنظام 24 ساعة.\n"
        "مثال: 14:30"
    )

    return ASK_TIME


async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_text = update.message.text.strip()

    try:
        parsed_time = datetime.strptime(time_text, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "الوقت غير صحيح.\n"
            "اكتب مثلًا: 14:30"
        )
        return ASK_TIME

    formatted_time = parsed_time.strftime("%H:%M")
    lessons = load_lessons()

    lesson_id = (
        max([lesson.get("id", 0) for lesson in lessons], default=0) + 1
    )

    lesson = {
        "id": lesson_id,
        "name": context.user_data["lesson_name"],
        "day": context.user_data["lesson_day"],
        "time": formatted_time,
        "chat_id": update.effective_chat.id,
    }

    lessons.append(lesson)
    save_lessons(lessons)
    schedule_lesson(context.application, lesson)

    await update.message.reply_text(
        "تمت إضافة الحصة ✅\n\n"
        f"📚 الحصة: {lesson['name']}\n"
        f"📅 اليوم: {DAY_NAMES[lesson['day']]}\n"
        f"⏰ الوقت: {lesson['time']}\n\n"
        "سيصلك تذكير قبل يوم، وقبل نصف ساعة، وقبل 15 دقيقة."
    )

    context.user_data.clear()
    return ConversationHandler.END


async def list_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lessons = [
        lesson
        for lesson in load_lessons()
        if lesson["chat_id"] == update.effective_chat.id
    ]

    if not lessons:
        await update.message.reply_text("لا توجد حصص محفوظة.")
        return

    text = "📚 جدول الحصص الأسبوعي:\n\n"

    for index, lesson in enumerate(lessons, start=1):
        text += (
            f"{index}. {lesson['name']}\n"
            f"📅 {DAY_NAMES[lesson['day']]}\n"
            f"⏰ {lesson['time']}\n\n"
        )

    await update.message.reply_text(text)


async def delete_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "اكتب رقم الحصة بعد الأمر.\n"
            "مثال: /delete 1\n\n"
            "استخدم /list لمعرفة الرقم."
        )
        return

    try:
        selected_number = int(context.args[0])
    except ValueError:
        await update.message.reply_text("رقم الحصة غير صحيح.")
        return

    all_lessons = load_lessons()
    user_lessons = [
        lesson
        for lesson in all_lessons
        if lesson["chat_id"] == update.effective_chat.id
    ]

    if selected_number < 1 or selected_number > len(user_lessons):
        await update.message.reply_text("لا توجد حصة بهذا الرقم.")
        return

    deleted = user_lessons[selected_number - 1]

    all_lessons = [
        lesson
        for lesson in all_lessons
        if lesson["id"] != deleted["id"]
    ]

    save_lessons(all_lessons)

    job_prefix = f"lesson_{deleted['id']}"

    for job in context.application.job_queue.jobs():
        if job.name and job.name.startswith(job_prefix):
            job.schedule_removal()

    await update.message.reply_text(
        f"تم حذف حصة {deleted['name']} ✅"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("تم إلغاء العملية.")
    return ConversationHandler.END


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN غير موجود في Environment Variables")

    application = (
        Application.builder()
        .token(TOKEN)
        .post_init(restore_jobs)
        .build()
    )

    add_handler = ConversationHandler(
        entry_points=[CommandHandler("add", add_lesson)],
        states={
            ASK_NAME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_name,
                )
            ],
            ASK_DAY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_day,
                )
            ],
            ASK_TIME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    receive_time,
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(add_handler)
    application.add_handler(CommandHandler("list", list_lessons))
    application.add_handler(CommandHandler("delete", delete_lesson))
    application.add_handler(CommandHandler("cancel", cancel))

    application.run_polling()


if __name__ == "__main__":
    main()
