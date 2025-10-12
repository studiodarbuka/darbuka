import discord
from discord import app_commands
import datetime
import os
import asyncio
import json
import pytz

# -----------------------------
# 初期設定
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# -----------------------------
# 永続化ディレクトリ
# -----------------------------
PERSISTENT_DIR = "/data/schedulebot"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "vote_data.json")
REMINDER_FILE = os.path.join(PERSISTENT_DIR, "reminders.json")

file_lock = asyncio.Lock()

# -----------------------------
# データ永続化関数
# -----------------------------
def _atomic_write(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

async def save_json(file, data):
    async with file_lock:
        await asyncio.to_thread(_atomic_write, file, data)

async def load_json(file, default):
    if not os.path.exists(file):
        return default
    async with file_lock:
        return await asyncio.to_thread(lambda: json.load(open(file, "r", encoding="utf-8")))

# -----------------------------
# 起動時データ読み込み
# -----------------------------
vote_data = asyncio.run(load_json(VOTE_FILE, {}))
scheduled_weeks = asyncio.run(load_json(REMINDER_FILE, {"scheduled": []}))["scheduled"]

# -----------------------------
# VoteView
# -----------------------------
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def register_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}

        # 他の選択肢から削除
        for k in vote_data[message_id][self.date_str]:
            if user_id in vote_data[message_id][self.date_str][k]:
                vote_data[message_id][self.date_str][k].remove(user_id)

        # 新しい選択肢に追加
        vote_data[message_id][self.date_str][status].append(user_id)
        await save_json(VOTE_FILE, vote_data)

        # Embed更新
        def ids_to_display(ids):
            names = []
            for uid in ids:
                member = interaction.guild.get_member(int(uid))
                names.append(member.display_name if member else f"<@{uid}>")
            return "\n".join(names) if names else "なし"

        embed = interaction.message.embeds[0]
        for idx, k in enumerate(["参加(🟢)", "調整可(🟡)", "不可(🔴)"]):
            embed.set_field_at(idx, name=k, value=ids_to_display(vote_data[message_id][self.date_str][k]), inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

        # 参加3人以上で確定通知
        if len(vote_data[message_id][self.date_str]["参加(🟢)"]) >= 3:
            await interaction.channel.send(f"✅ {self.date_str} は3人以上が参加予定！日程確定です！")

    # ボタン
    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.blurple)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可(🔴)")

# -----------------------------
# /schedule コマンド
# -----------------------------
@tree.command(name="schedule", description="日程調整を開始します")
async def schedule(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    tz = pytz.timezone("Asia/Tokyo")
    today = datetime.datetime.now(tz).date()
    target = today + datetime.timedelta(weeks=3)
    days_to_sunday = (6 - target.weekday()) % 7
    start_date = target + datetime.timedelta(days=days_to_sunday)

    scheduled_weeks.append({
        "channel_name": "日程",
        "start_date": start_date.strftime("%Y-%m-%d"),
        "reminded_2w": False,
        "reminded_1w": False
    })
    await save_json(REMINDER_FILE, {"scheduled": scheduled_weeks})

    dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]
    for d in dates:
        embed = discord.Embed(title=f"【日程候補】{d}", description="以下のボタンで投票してください")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        channel = discord.utils.get(interaction.guild.text_channels, name="日程")
        if channel:
            await channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(f"📅 {start_date.strftime('%m/%d(%a)')} からの1週間の日程候補を作成しました！", ephemeral=True)

# -----------------------------
# /event_now コマンド
# -----------------------------
@tree.command(name="event_now", description="突発イベントを作成")
@app_commands.describe(
    title="イベント名",
    description="詳細（任意）",
    date="投票日程（複数可、カンマ区切り、形式: YYYY-MM-DD）"
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
        for guild in bot.guilds:
            channel = discord.utils.get(guild.text_channels, name="日程")
            if channel:
                await channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(f"🚨 イベント「{title}」を作成しました！", ephemeral=True)

# -----------------------------
# 自動スケジュール送信タスク（毎週日曜10時）
# -----------------------------
async def scheduler_task():
    tz = pytz.timezone("Asia/Tokyo")
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.datetime.now(tz)
        if now.weekday() == 6 and now.hour == 10 and now.minute == 0:  # 日曜10:00
            today = now.date()
            target = today + datetime.timedelta(weeks=3)
            days_to_sunday = (6 - target.weekday()) % 7
            start_date = target + datetime.timedelta(days=days_to_sunday)

            dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]
            for guild in bot.guilds:
                channel = discord.utils.get(guild.text_channels, name="日程")
                if channel:
                    for d in dates:
                        embed = discord.Embed(title=f"【日程候補】{d}", description="以下のボタンで投票してください")
                        embed.add_field(name="参加(🟢)", value="なし", inline=False)
                        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
                        embed.add_field(name="不可(🔴)", value="なし", inline=False)
                        await channel.send(embed=embed, view=VoteView(d))

            scheduled_weeks.append({
                "channel_name": "日程",
                "start_date": start_date.strftime("%Y-%m-%d"),
                "reminded_2w": False,
                "reminded_1w": False
            })
            await save_json(REMINDER_FILE, {"scheduled": scheduled_weeks})
            await asyncio.sleep(60)  # 1分待機して同じ分に再送しない
        await asyncio.sleep(30)

# -----------------------------
# Bot起動
# -----------------------------
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

# -----------------------------
# 実行
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)
