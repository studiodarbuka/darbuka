import os
import discord
import json
import asyncio
import datetime
import pytz
from discord.ext import tasks, commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# ===== 基本設定 =====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== Render対応 永続化ディレクトリ =====
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")

# ===== タイムゾーン =====
JST = pytz.timezone("Asia/Tokyo")

# ===== 投票データ =====
vote_data = {}

# ===== ユーティリティ =====
def load_votes():
    global vote_data
    if os.path.exists(VOTE_FILE):
        with open(VOTE_FILE, "r", encoding="utf-8") as f:
            vote_data = json.load(f)
    else:
        vote_data = {}

def save_votes():
    with open(VOTE_FILE, "w", encoding="utf-8") as f:
        json.dump(vote_data, f, ensure_ascii=False, indent=2)

def get_schedule_start():
    """3週間後の日曜を取得"""
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    target = today + datetime.timedelta(days=days_until_sunday + 14)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

def generate_table():
    """表形式で現在の投票状況を出力"""
    table = "📅 **投票状況**\n"
    table += "```\n日程           | 参加 | 調整 | 不可\n"
    table += "--------------------------------\n"
    for date, votes in vote_data.items():
        s = sum(1 for v in votes.values() if v == "参加")
        m = sum(1 for v in votes.values() if v == "調整")
        n = sum(1 for v in votes.values() if v == "不可")
        table += f"{date} |  {s:^3} |  {m:^3} |  {n:^3}\n"
    table += "```"
    return table

# ===== 投稿処理 =====
async def send_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    week = generate_week_schedule()
    global vote_data
    vote_data = {date: {} for date in week}
    save_votes()

    msg = "📅 **三週間後の予定（投票開始）**\n"
    msg += "\n".join([f"・{d}" for d in week])
    msg += "\n\nリアクションで投票してください！\n✅ = 参加 / 🤔 = 調整 / ❌ = 不可"

    sent = await channel.send(msg)
    for emoji in ["✅", "🤔", "❌"]:
        await sent.add_reaction(emoji)
    print("✅ 三週間後の予定を投稿しました。")

async def send_reminder():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="投票催促")
    if not channel:
        print("⚠️ チャンネル「投票催促」が見つかりません。")
        return

    msg = "⏰ **2週間前になりました！投票をお願いします！**"
    await channel.send(msg)
    await channel.send(generate_table())
    print("✅ 2週間前の催促を送信しました。")

async def send_final_reminder():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="投票催促")
    if not channel:
        print("⚠️ チャンネル「投票催促」が見つかりません。")
        return

    msg = "⚠️ **1週間前です！未投票の方は至急お願いします！**"
    await channel.send(msg)
    await channel.send(generate_table())
    print("✅ 1週間前の最終催促を送信しました。")

# ===== スケジューラー =====
scheduler = AsyncIOScheduler(timezone=JST)
scheduler.add_job(send_schedule, CronTrigger(day_of_week="sun", hour=10, minute=0))
scheduler.add_job(send_reminder, CronTrigger(day_of_week="sun", hour=10, minute=0, week="*/1"))
scheduler.add_job(send_final_reminder, CronTrigger(day_of_week="sun", hour=10, minute=0, week="*/2"))

# ===== 起動時 =====
@bot.event
async def on_ready():
    load_votes()
    if not scheduler.running:
        scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started.")

# ===== 投票リアクション =====
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    msg = reaction.message
    if not any(keyword in msg.content for keyword in ["三週間後の予定", "投票開始"]):
        return

    emoji_map = {"✅": "参加", "🤔": "調整", "❌": "不可"}
    if reaction.emoji not in emoji_map:
        return

    for date in vote_data.keys():
        if date in msg.content:
            vote_data[date][str(user)] = emoji_map[reaction.emoji]
            save_votes()
            break

# ===== メイン =====
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
