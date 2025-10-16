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

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== 永続保存設定 ======
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")

# ====== タイムゾーン ======
JST = pytz.timezone("Asia/Tokyo")

# ====== 投票データ ======
vote_data = {}  # { "2025-11-05 (Sun)": { "user_id": "参加/調整/不可" } }

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
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    target = today + datetime.timedelta(days=days_until_sunday + 14)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

# ====== 投票状況テーブル ======
def generate_table_with_users():
    table = "📊 **投票状況**\n"
    for date, votes in vote_data.items():
        s_list = [f"<@{uid}>" for uid, v in votes.items() if v == "参加"]
        m_list = [f"<@{uid}>" for uid, v in votes.items() if v == "調整"]
        n_list = [f"<@{uid}>" for uid, v in votes.items() if v == "不可"]

        table += f"**{date}**\n"
        table += f"✅ 参加 ({len(s_list)}): {' '.join(s_list) if s_list else 'なし'}\n"
        table += f"🤔 調整 ({len(m_list)}): {' '.join(m_list) if m_list else 'なし'}\n"
        table += f"❌ 不可 ({len(n_list)}): {' '.join(n_list) if n_list else 'なし'}\n"
        table += "--------------------------------\n"
    return table

# ====== 投票ボタン ======
class VoteView(discord.ui.View):
    def __init__(self, date):
        super().__init__(timeout=None)
        self.date = date

    @discord.ui.button(label="参加 ✅", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        vote_data[self.date][str(interaction.user.id)] = "参加"
        save_votes()
        await interaction.response.send_message(f"{interaction.user.name} が {self.date} に「参加 ✅」を投票しました！", ephemeral=True)

    @discord.ui.button(label="調整 🤔", style=discord.ButtonStyle.primary)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        vote_data[self.date][str(interaction.user.id)] = "調整"
        save_votes()
        await interaction.response.send_message(f"{interaction.user.name} が {self.date} に「調整 🤔」を投票しました！", ephemeral=True)

    @discord.ui.button(label="不可 ❌", style=discord.ButtonStyle.danger)
    async def cannot(self, interaction: discord.Interaction, button: discord.ui.Button):
        vote_data[self.date][str(interaction.user.id)] = "不可"
        save_votes()
        await interaction.response.send_message(f"{interaction.user.name} が {self.date} に「不可 ❌」を投票しました！", ephemeral=True)

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

    for date in week:
        msg = f"📅 **三週間後の日程: {date}（投票開始）**"
        await channel.send(msg, view=VoteView(date))

    print("✅ Step1: 三週間前スケジュール投稿完了。")

async def send_step2_remind():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    msg = "⏰ **2週間前になりました！投票状況を確認してください！**"
    await channel.send(msg)
    await channel.send(generate_table_with_users())
    print("✅ Step2: 2週間前リマインド送信完了。")

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

    now = datetime.datetime.now(JST)
    # テスト用: 今日 13:42 に三週間前通知
    test_time_step1 = now.replace(hour=13, minute=42, second=0, microsecond=0)
    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=test_time_step1))

    # テスト用: 今日 13:45 に二週間前リマインド
    test_time_step2 = now.replace(hour=13, minute=45, second=0, microsecond=0)
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=test_time_step2))

    scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started.")

# ====== メイン ======
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
