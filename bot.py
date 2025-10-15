import os
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

# ===== 基本設定 =====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # commands.BotはすでにCommandTreeを持つので再作成不要

# ===== 永続保存 =====
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")

# ===== タイムゾーン =====
JST = pytz.timezone("Asia/Tokyo")

# ===== 投票データ =====
def load_votes():
    if os.path.exists(VOTE_FILE):
        with open(VOTE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_votes(vote_data):
    with open(VOTE_FILE, "w", encoding="utf-8") as f:
        json.dump(vote_data, f, ensure_ascii=False, indent=2)

vote_data = load_votes()

# ===== ユーティリティ =====
def get_schedule_start():
    """3週間後の日曜を取得"""
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    target = today + datetime.timedelta(days=days_until_sunday + 14)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

def generate_vote_table(vote_data):
    table = "📊 **投票状況**\n```\n日程           | 参加 | 調整 | 不可\n"
    table += "--------------------------------\n"
    for date, votes in vote_data.items():
        s = sum(1 for v in votes.values() if v == "参加")
        m = sum(1 for v in votes.values() if v == "調整")
        n = sum(1 for v in votes.values() if v == "不可")
        table += f"{date} |  {s:^3} |  {m:^3} |  {n:^3}\n"
    table += "```"
    return table

# ===== Step1: 毎週日曜 10:00に日程投稿 =====
async def send_week_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
        return

    week = generate_week_schedule()
    global vote_data
    vote_data = {date: {} for date in week}
    save_votes(vote_data)

    msg = "📅 **三週間後の予定（投票開始）**\n\n" + "\n".join([f"・{d}" for d in week])
    msg += "\n\nリアクションで投票してください！\n✅ = 参加 / 🤔 = 調整 / ❌ = 不可"

    sent = await channel.send(msg)
    for emoji in ["✅", "🤔", "❌"]:
        await sent.add_reaction(emoji)
    print("✅ 週間日程投稿完了")

# ===== Step2: 2週間前リマインド（テキスト表） =====
async def remind_2weeks():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
        return

    msg = "⏰ **2週間前リマインドです！投票状況を確認してください**\n\n"
    await channel.send(msg + generate_vote_table(vote_data))
    print("✅ 2週間前リマインド送信完了")

# ===== リアクション処理 =====
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
            save_votes(vote_data)
            break

# ===== /Remind コマンド（手動テスト用） =====
@tree.command(name="remind", description="2週間前リマインドを手動で送信")
async def remind_command(interaction: discord.Interaction):
    await interaction.response.send_message("⏰ リマインド送信中...", ephemeral=True)
    await remind_2weeks()

# ===== 起動時 =====
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠️ コマンド同期エラー: {e}")

# ===== スケジューラー設定 =====
scheduler = AsyncIOScheduler(timezone=JST)
# 毎週日曜 10:00に送信
scheduler.add_job(send_week_schedule, CronTrigger(day_of_week="sun", hour=10, minute=0))
# Step2: テスト用に今日15:40に送信
now = datetime.datetime.now(JST)
test_time = now.replace(hour=15, minute=40, second=0, microsecond=0)
if test_time < now:
    test_time = now + datetime.timedelta(minutes=1)
scheduler.add_job(remind_2weeks, DateTrigger(test_time))
scheduler.start()

# ===== メイン =====
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
