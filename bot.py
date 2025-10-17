import os
import discord
from discord.ext import commands
from discord import app_commands
import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# =========================
# 基本設定
# =========================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree
JST = pytz.timezone("Asia/Tokyo")

# =========================
# Step1: 三週間後の週チャンネル作成
# =========================
def get_three_weeks_later_sunday():
    """現在日付から3週間後の日曜を取得"""
    today = datetime.datetime.now(JST).date()
    # 今日の曜日 (0=月曜, 6=日曜)
    days_until_sunday = (6 - today.weekday()) % 7
    # 3週間後の日曜
    target = today + datetime.timedelta(days=days_until_sunday + 21)
    return target

def get_week_of_month(date):
    """その月の第何週目かを取得"""
    first_day = date.replace(day=1)
    first_weekday = first_day.weekday()  # 0=月曜
    week_num = (date.day + first_weekday - 1) // 7 + 1
    return week_num

async def send_step1_schedule():
    await bot.wait_until_ready()
    guild = bot.guilds[0]  # テスト用：最初のサーバー取得

    # 三週間後の日曜取得
    three_weeks_sunday = get_three_weeks_later_sunday()
    week_number = get_week_of_month(three_weeks_sunday)
    channel_name = f"{three_weeks_sunday.month}月第{week_number}週"

    # カテゴリと権限設定
    categories = {
        "初級": ["初級", "管理者"],
        "中級": ["中級", "管理者"]
    }

    for key, roles in categories.items():
        category = discord.utils.get(guild.categories, name=key)
        if not category:
            category = await guild.create_category(name=key)

        # 権限設定
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False)}
        for role_name in roles:
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        # チャンネル作成
        await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)

    print(f"✅ Step1: {channel_name} チャンネル作成完了")

# =========================
# on_ready + テストスケジュール
# =========================
@bot.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {bot.user}")

    now = datetime.datetime.now(JST)
    scheduler = AsyncIOScheduler(timezone=JST)

    # テスト用：今から10秒後に実行
    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=now + datetime.timedelta(seconds=10)))

    scheduler.start()
    print("✅ Scheduler started (Step1 テスト用)")

# =========================
# メイン
# =========================
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
