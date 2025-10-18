import os
import discord
from discord.ext import commands
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ===== 基本設定 =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ===== 永続保存 =====
DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)
VOTE_FILE = os.path.join(DATA_DIR, "votes.json")
JST = pytz.timezone("Asia/Tokyo")

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

# ===== 日付関連 =====
def get_schedule_start():
    today = datetime.datetime.now(JST)
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - datetime.timedelta(days=days_since_sunday)
    target = this_sunday + datetime.timedelta(weeks=3)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

def get_week_name(date):
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    return f"{month}月第{week_number}週"

# ===== 投票ビュー =====
class VoteView(discord.ui.View):
    def __init__(self, level, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.level = level

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        user = interaction.user.display_name
        level = self.level
        date = self.date_str

        if level not in vote_data:
            vote_data[level] = {}
        if date not in vote_data[level]:
            vote_data[level][date] = {"🟢": [], "🟡": [], "🔴": []}

        # 他の状態から削除
        for k in vote_data[level][date]:
            if user in vote_data[level][date][k]:
                vote_data[level][date][k].remove(user)

        vote_data[level][date][status].append(user)
        save_votes()

        embed = discord.Embed(title=f"📅 {level} - {date}")
        for emoji, label in {"🟢": "参加", "🟡": "オンライン可", "🔴": "不可"}.items():
            users = vote_data[level][date][emoji]
            embed.add_field(name=f"{emoji} {label}（{len(users)}人）", value="\n".join(users) if users else "なし", inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "🟢")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "🟡")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "🔴")

# ===== Step1: 3週間後の投票作成 =====
async def send_step1_schedule():
    await bot.wait_until_ready()
    guild = bot.guilds[0]

    category_beginner = discord.utils.get(guild.categories, name="初級")
    category_intermediate = discord.utils.get(guild.categories, name="中級")

    if not category_beginner or not category_intermediate:
        print("⚠️ カテゴリ「初級」「中級」が見つかりません。")
        return

    start = get_schedule_start()
    week_name = get_week_name(start)
    week = generate_week_schedule()

    channels = {}
    for level, category in {"初級": category_beginner, "中級": category_intermediate}.items():
        ch_name = f"{week_name}-{level}"
        existing = discord.utils.get(guild.text_channels, name=ch_name)
        ch = existing or await guild.create_text_channel(ch_name, category=category)
        channels[level] = ch

        vote_data[level] = {}

        for date in week:
            embed = discord.Embed(title=f"📅 {level} - {date}")
            embed.add_field(name="🟢 参加（0人）", value="なし", inline=False)
            embed.add_field(name="🟡 オンライン可（0人）", value="なし", inline=False)
            embed.add_field(name="🔴 不可（0人）", value="なし", inline=False)

            view = VoteView(level, date)
            await ch.send(embed=embed, view=view)

            vote_data[level][date] = {"🟢": [], "🟡": [], "🔴": []}

    save_votes()
    print("✅ Step1 完了：投票メッセージを送信しました。")

# ===== Step2: 2週間前リマインド =====
async def send_step2_reminder():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    print("🟡 Step2 実行開始")

    for level, dates in vote_data.items():
        week_name = "11月第1週"  # 実際は自動算出可能
        text = f"📢【{week_name} {level}リマインド】\n\n📅 日程ごとの参加状況：\n\n"

        for date_str, reactions in dates.items():
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
            text += f"{date_str}（{weekday_jp}）\n"
            text += f"🟢 参加：{', '.join(reactions['🟢']) if reactions['🟢'] else 'なし'}\n"
            text += f"🟡 オンライン可：{', '.join(reactions['🟡']) if reactions['🟡'] else 'なし'}\n"
            text += f"🔴 不可：{', '.join(reactions['🔴']) if reactions['🔴'] else 'なし'}\n\n"

        target_channel = discord.utils.get(guild.text_channels, name__contains=level)
        if target_channel:
            await target_channel.send(text)
            print(f"✅ {level} にリマインド送信")
        else:
            print(f"⚠ {level} のチャンネルが見つかりません")

# ===== 起動イベント =====
@bot.event
async def on_ready():
    print(f"✅ ログイン完了: {bot.user}")

    scheduler = AsyncIOScheduler(timezone=JST)

    now = datetime.datetime.now(JST)
    step1_time = now + datetime.timedelta(seconds=5)
    step2_time = now + datetime.timedelta(seconds=20)

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=step1_time))
    scheduler.add_job(send_step2_reminder, DateTrigger(run_date=step2_time))

    scheduler.start()
    print(f"⏰ Step1: {step1_time.strftime('%H:%M:%S')} / Step2: {step2_time.strftime('%H:%M:%S')} に実行予定")

load_votes()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
