import os
import discord
from discord import app_commands
import asyncio
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from discord.ext import commands

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = app_commands.CommandTree(bot)

# ====== 永続保存設定 (Render対応) ======
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")

# ====== タイムゾーン ======
JST = pytz.timezone("Asia/Tokyo")

# ====== 投票データ ======
vote_data = {}

# ====== ユーティリティ ======
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

# ====== メッセージ送信 ======
async def send_schedule(test_channel_name=None):
    await bot.wait_until_ready()
    channel_name = test_channel_name or "wqwq"
    channel = discord.utils.get(bot.get_all_channels(), name=channel_name)
    if not channel:
        print(f"⚠️ チャンネル「{channel_name}」が見つかりません。")
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
    print("✅ 自動スケジュール投稿完了。")

# ====== 突発イベント ======
@tree.command(name="event_now", description="突発イベントをすぐ通知します。")
async def event_now(interaction: discord.Interaction, 内容: str):
    channel = discord.utils.get(interaction.guild.channels, name="突発イベント")
    if not channel:
        await interaction.response.send_message("⚠️ チャンネル「突発イベント」が見つかりません。", ephemeral=True)
        return

    msg = f"🚨 **突発イベント発生！**\n{内容}"
    await channel.send(msg)
    await interaction.response.send_message("✅ 突発イベントを送信しました！", ephemeral=True)

# ====== 手動スケジュール作成 ======
@tree.command(name="schedule", description="手動で日程投票を開始します。")
async def schedule(interaction: discord.Interaction):
    await interaction.response.send_message("📅 手動で日程投票を開始します。", ephemeral=True)
    await send_schedule("wqwq")

# ====== スケジューラー設定 ======
scheduler = AsyncIOScheduler(timezone=JST)

# 毎週日曜 10:00 に通常スケジュール
scheduler.add_job(send_schedule, CronTrigger(day_of_week="sun", hour=10, minute=0))

# ====== テスト用：今日の12:15に一度だけ投稿 ======
now = datetime.datetime.now(JST)
test_time = now.replace(hour=12, minute=15, second=0, microsecond=0)
if test_time < now:
    test_time += datetime.timedelta(days=0)  # 今日が過ぎていればすぐは流れない
scheduler.add_job(send_schedule, DateTrigger(run_date=test_time), kwargs={"test_channel_name": "wqwq"})

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

# ====== 起動時 ======
@bot.event
async def on_ready():
    load_votes()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠️ コマンド同期エラー: {e}")
    if not scheduler.running:
        scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started.")

# ====== メイン ======
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
