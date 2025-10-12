import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import datetime
import os
import asyncio

# -----------------------------
# 初期設定
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# チャンネル名で自動検出
CHANNEL_NAME = "wqwq"

# -----------------------------
# 予定送信関数
# -----------------------------
async def send_week_schedule():
    # 今日から三週間後の日曜
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).date()
    target = today + datetime.timedelta(weeks=3)
    days_to_sunday = (6 - target.weekday()) % 7
    start_date = target + datetime.timedelta(days=days_to_sunday)

    # チャンネル取得
    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=CHANNEL_NAME)
        if channel:
            await channel.send(f"📅 【三週間後の日曜始まりの予定】{start_date.strftime('%m/%d(%a)')} からの1週間の日程候補です")
            # 1週間分の候補
            for i in range(7):
                day = start_date + datetime.timedelta(days=i)
                await channel.send(f"- {day.strftime('%m/%d(%a)')}: 予定候補")
            await channel.send("✅ 自動送信テスト完了！")
            print(f"✅ 予定を {channel.name} に送信しました")
            break

# -----------------------------
# Bot起動時処理
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

    # 今日の19:40 JST に送信
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    send_time = now.replace(hour=19, minute=40, second=0, microsecond=0)
    if send_time < now:
        send_time += datetime.timedelta(days=1)  # 過ぎていたら翌日

    scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")
    scheduler.add_job(lambda: asyncio.create_task(send_week_schedule()), trigger=DateTrigger(run_date=send_time))
    scheduler.start()
    print(f"⏰ 三週間後の日曜始まり予定を今日の19:40 JST に送信するスケジューラーを設定しました")

# -----------------------------
# 実行
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)
