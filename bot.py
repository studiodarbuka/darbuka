import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree  # すでに commands.Bot には CommandTree があるので再生成しない

# ====== 永続保存設定 ======
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")

# ====== タイムゾーン ======
JST = pytz.timezone("Asia/Tokyo")

# ====== 投票データ ======
vote_data = {}

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

# ====== スケジュール生成 ======
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
    table = "📊 **投票状況**\n"
    table += "```\n日程           | 参加 | 調整 | 不可\n"
    table += "--------------------------------\n"
    for date, votes in vote_data.items():
        s = sum(1 for v in votes.values() if v == "参加")
        m = sum(1 for v in votes.values() if v == "調整")
        n = sum(1 for v in votes.values() if v == "不可")
        table += f"{date} |  {s:^3} |  {m:^3} |  {n:^3}\n"
    table += "```"
    return table

# ====== メッセージ送信 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
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
    print("✅ Step1: 三週間前スケジュール投稿完了。")

async def send_step2_remind():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    msg = "⏰ **2週間前になりました！投票をお願いします！**"
    await channel.send(msg)
    await channel.send(generate_table())
    print("✅ Step2: 2週間前リマインド送信完了。")

# ====== Slash コマンド ======
@tree.command(name="schedule", description="手動で日程投票を開始します。")
async def schedule(interaction: discord.Interaction):
    await interaction.response.send_message("📅 手動で日程投票を開始します。", ephemeral=True)
    await send_step1_schedule()

@tree.command(name="event_now", description="突発イベントをすぐ通知します。")
async def event_now(interaction: discord.Interaction, 内容: str):
    channel = discord.utils.get(interaction.guild.channels, name="突発イベント")
    if not channel:
        await interaction.response.send_message("⚠️ チャンネル「突発イベント」が見つかりません。", ephemeral=True)
        return
    msg = f"🚨 **突発イベント発生！**\n{内容}"
    await channel.send(msg)
    await interaction.response.send_message("✅ 突発イベントを送信しました！", ephemeral=True)

# ====== リアクション処理 ======
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

# ====== on_ready ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠️ コマンド同期エラー: {e}")

    # Step1: 毎週日曜 10:00 JST に自動投稿
    scheduler.add_job(send_step1_schedule, CronTrigger(day_of_week="sun", hour=10, minute=0))

    # Step2: テスト用に今日 15:50 に送信
    now = datetime.datetime.now(JST)
    test_time = now.replace(hour=15, minute=50, second=0, microsecond=0)
    if test_time < now:
        test_time += datetime.timedelta(days=0)  # 過ぎていれば今日再送信
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=test_time))

    scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started.")

# ====== メイン ======
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
