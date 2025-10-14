import os
import discord
import json
import asyncio
import datetime
import pytz
from discord.ext import tasks
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from discord import app_commands

# =============================
# ===== Bot 初期設定 =====
# =============================
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# =============================
# ===== ディレクトリ・永続化 =====
# =============================
PERSISTENT_DIR = "/opt/render/project/src/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")
REMINDER_FILE = os.path.join(PERSISTENT_DIR, "reminders.json")

# =============================
# ===== タイムゾーン =====
# =============================
JST = pytz.timezone("Asia/Tokyo")

# =============================
# ===== データ読み書き =====
# =============================
def load_json(file, default):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        return default

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

vote_data = load_json(VOTE_FILE, {})
scheduled_weeks = load_json(REMINDER_FILE, {"scheduled": []})["scheduled"]

# =============================
# ===== VoteView (ボタン投票) =====
# =============================
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.blurple)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可(🔴)")

    async def register_vote(self, interaction: discord.Interaction, status: str):
        user = interaction.user.name
        message_id = str(interaction.message.id)
        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}

        # 他の選択肢から削除
        for k in vote_data[message_id][self.date_str]:
            if user in vote_data[message_id][self.date_str][k]:
                vote_data[message_id][self.date_str][k].remove(user)

        # 新しい選択肢に追加
        vote_data[message_id][self.date_str][status].append(user)
        save_json(VOTE_FILE, vote_data)

        # Embed更新
        embed = interaction.message.embeds[0]
        for idx, k in enumerate(["参加(🟢)", "調整可(🟡)", "不可(🔴)"]):
            users = vote_data[message_id][self.date_str][k]
            embed.set_field_at(idx, name=k, value="\n".join(users) if users else "なし", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

        # 参加3人以上で確定通知
        if len(vote_data[message_id][self.date_str]["参加(🟢)"]) >= 3:
            await interaction.channel.send(f"✅ {self.date_str} は3人以上が参加予定！日程確定です！")

# =============================
# ===== ユーティリティ関数 =====
# =============================
def generate_week_schedule():
    """3週間後の日曜を基準に1週間分の日程を生成"""
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    start = today + datetime.timedelta(days=days_until_sunday + 14)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

# =============================
# ===== /schedule コマンド =====
# =============================
@tree.command(name="schedule", description="日程調整を開始します")
async def schedule(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    week = generate_week_schedule()
    global vote_data
    vote_data = {date: {} for date in week}
    save_json(VOTE_FILE, vote_data)

    for date in week:
        embed = discord.Embed(title=f"【日程候補】{date}", description="以下のボタンで投票してください")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        await interaction.channel.send(embed=embed, view=VoteView(date))

    await interaction.followup.send("📅 日程候補を投稿しました！", ephemeral=True)

# =============================
# ===== /event_now コマンド =====
# =============================
@tree.command(name="event_now", description="突発イベントを作成")
@app_commands.describe(
    title="イベント名",
    description="詳細（任意）",
    date="投票日程（カンマ区切り、YYYY-MM-DD形式）"
)
async def event_now(interaction: discord.Interaction, title: str, date: str, description: str = ""):
    await interaction.response.defer(ephemeral=True)
    dates = []
    for d in date.split(","):
        d_clean = d.strip()
        parsed = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                parsed = datetime.datetime.strptime(d_clean, fmt).strftime("%m/%d(%a)")
                break
            except ValueError:
                continue
        if not parsed:
            await interaction.followup.send(f"⚠️ 日付フォーマットが不正です: {d_clean}", ephemeral=True)
            return
        dates.append(parsed)

    for d in dates:
        embed = discord.Embed(title=f"【突発イベント】{title} - {d}", description=description or "詳細なし")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        await interaction.channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(f"🚨 イベント「{title}」を作成しました！", ephemeral=True)

# =============================
# ===== バックグラウンドタスク（自動リマインド・確定通知） =====
# =============================
async def scheduler_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        today = datetime.date.today()
        for s in scheduled_weeks:
            start_date = datetime.datetime.strptime(s["start_date"], "%Y-%m-%d").date()

            # 2週間前リマインド
            if not s.get("reminded_2w") and today == start_date - datetime.timedelta(weeks=2):
                channel = bot.get_channel(s["channel_id"])
                if channel:
                    await channel.send("📢 日程調整のリマインドです！投票がまだの方はお願いします！")
                    s["reminded_2w"] = True

            # 1週間前確定通知
            if not s.get("reminded_1w") and today == start_date - datetime.timedelta(weeks=1):
                channel = bot.get_channel(s["channel_id"])
                if channel:
                    await channel.send("📅 予定表確定の確認です！参加者3人未満の日は催促します。")
                    s["reminded_1w"] = True

        save_json(REMINDER_FILE, {"scheduled": scheduled_weeks})
        await asyncio.sleep(24*60*60)  # 1日ごとチェック

# =============================
# ===== on_ready =====
# =============================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await tree.sync()
        print("✅ Slash commands synced!")
    except Exception as e:
        print(f"❌ Sync error: {e}")
    bot.loop.create_task(scheduler_task())
    print("⏰ Scheduler task started")

# =============================
# ===== 実行 =====
# =============================
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)
