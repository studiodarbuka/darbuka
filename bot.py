import os
import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import datetime
import pytz
import json
import asyncio

# ===== 基本設定 =====
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler()
JST = pytz.timezone("Asia/Tokyo")

# ===== 投票データ保存用 =====
VOTES_FILE = "votes.json"


# ===== 日本語曜日変換 =====
def get_japanese_weekday(date_str):
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    return weekdays[dt.weekday()]


# ====== 投票ボタンView ======
class VoteView(discord.ui.View):
    def __init__(self, date_str, level):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.level = level

    @discord.ui.button(label="✅ 参加", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user.name
        update_vote(self.level, self.date_str, user, "参加")
        await interaction.response.send_message(f"{user} さんが「参加」を選択しました。", ephemeral=True)

    @discord.ui.button(label="💻 オンライン可", style=discord.ButtonStyle.primary)
    async def online(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user.name
        update_vote(self.level, self.date_str, user, "オンライン")
        await interaction.response.send_message(f"{user} さんが「オンライン可」を選択しました。", ephemeral=True)

    @discord.ui.button(label="❌ 不可", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user.name
        update_vote(self.level, self.date_str, user, "不可")
        await interaction.response.send_message(f"{user} さんが「不可」を選択しました。", ephemeral=True)


# ===== 投票データ更新関数 =====
def update_vote(level, date, user, status):
    if not os.path.exists(VOTES_FILE):
        votes = []
    else:
        with open(VOTES_FILE, "r", encoding="utf-8") as f:
            votes = json.load(f)

    found = False
    for v in votes:
        if v["level"] == level and v["date"] == date:
            v["participants"][user] = status
            found = True
            break

    if not found:
        votes.append({"level": level, "date": date, "participants": {user: status}})

    with open(VOTES_FILE, "w", encoding="utf-8") as f:
        json.dump(votes, f, ensure_ascii=False, indent=2)


# ===== Step1: 投票チャンネル作成 & 投票投稿 =====
async def send_step1_schedule():
    now = datetime.datetime.now(JST)
    # 今週の日曜を1週目として、3週後の日曜を算出
    this_sunday = now - datetime.timedelta(days=now.weekday() + 1)
    target_start = this_sunday + datetime.timedelta(weeks=3)

    month_name = f"{target_start.month}月第{((target_start.day - 1)//7)+1}週"

    for guild in bot.guilds:
        category = discord.utils.get(guild.categories, name="スケジュール") or await guild.create_category("スケジュール")

        for level in ["初級", "中級"]:
            channel_name = f"{month_name}-{level}"
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
            }
            channel = await guild.create_text_channel(channel_name, category=category, overwrites=overwrites)

            embed = discord.Embed(
                title=f"🗓️ {month_name} ({level}) 投票",
                description="下のボタンで出欠を登録してください！",
                color=discord.Color.green()
            )

            for i in range(7):
                day = target_start + datetime.timedelta(days=i)
                weekday = ["日", "月", "火", "水", "木", "金", "土"][day.weekday()]
                embed.add_field(name=f"{day.strftime('%Y-%m-%d')}（{weekday}）", value="未投票", inline=False)

                view = VoteView(day.strftime("%Y-%m-%d"), level)
                await channel.send(embed=embed, view=view)


# ===== Step2: 二週間前リマインド =====
async def send_step2_reminder():
    now = datetime.datetime.now(JST)
    this_sunday = now - datetime.timedelta(days=now.weekday() + 1)
    target_start = this_sunday + datetime.timedelta(weeks=1)
    month_name = f"{target_start.month}月第{((target_start.day - 1)//7)+1}週"

    for guild in bot.guilds:
        if not os.path.exists(VOTES_FILE):
            continue
        with open(VOTES_FILE, "r", encoding="utf-8") as f:
            votes = json.load(f)

        for level in ["初級", "中級"]:
            channel_name = f"{month_name}-{level}"
            channel = discord.utils.get(guild.text_channels, name=channel_name)
            if not channel:
                continue

            level_votes = [v for v in votes if v["level"] == level]
            if not level_votes:
                await channel.send("⚠️ まだ投票データがありません。")
                continue

            lines = [f"🗓️ **{month_name} ({level}) 二週間前リマインド**", ""]
            for v in level_votes:
                date = v["date"]
                weekday = get_japanese_weekday(date)
                participants = []
                for name, status in v["participants"].items():
                    emoji = "✅" if status == "参加" else "💻" if status == "オンライン" else "❌"
                    participants.append(f"{emoji} {name}")
                lines.append(f"📅 {date}（{weekday}）\n　" + ", ".join(participants))

            msg = "\n".join(lines)
            await channel.send(msg)


# ===== Step3: 1週間前確定通知（仮） =====
async def send_step3_confirm():
    await asyncio.sleep(1)  # 仮置き
    print("Step3仮処理完了")


# ===== Bot起動時のスケジュール設定 =====
@bot.event
async def on_ready():
    print("✅ Bot起動完了！")

    now = datetime.datetime.now(JST)

    # Step1 → 14:51実行
    step1_time = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if step1_time < now:
        step1_time += datetime.timedelta(days=1)
    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=step1_time))

    # Step2 → 14:55実行
    step2_time = now.replace(hour=12, minute=2, second=0, microsecond=0)
    if step2_time < now:
        step2_time += datetime.timedelta(days=1)
    scheduler.add_job(send_step2_reminder, DateTrigger(run_date=step2_time))

    scheduler.start()


# ===== 起動 =====
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
bot.run(TOKEN)
