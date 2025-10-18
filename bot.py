import os
import discord
from discord.ext import commands
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== 永続保存 ======
PERSISTENT_DIR = "./data"
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

# ====== 三週間後・日曜始まり週を算出 ======
def get_schedule_start():
    today = datetime.datetime.now(JST)
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - datetime.timedelta(days=days_since_sunday)
    target = this_sunday + datetime.timedelta(weeks=3)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a) 日本") for i in range(7)]

# ====== 月第N週の文字列を返す ======
def get_week_name(date):
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    return f"{month}月第{week_number}週"

# ====== 投票ボタン付きビュー ======
class VoteView(discord.ui.View):
    def __init__(self, date_str, msg_id):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.msg_id = msg_id

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_name = interaction.user.display_name

        if message_id not in vote_data:
            return
        if self.date_str not in vote_data[message_id]["dates"]:
            return

        # 既存投票解除
        for k, v in vote_data[message_id]["dates"][self.date_str].items():
            if user_name in v:
                v.remove(user_name)
        vote_data[message_id]["dates"][self.date_str][status].append(user_name)
        save_votes()

        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id]["dates"][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "なし", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step1: チャンネル作成 + 投票送信 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    guild = bot.guilds[0]

    # カテゴリ取得
    category_beginner = discord.utils.get(guild.categories, name="初級")
    category_intermediate = discord.utils.get(guild.categories, name="中級")
    if not category_beginner or not category_intermediate:
        print("⚠️ カテゴリ「初級」「中級」が見つかりません。")
        return

    start = get_schedule_start()
    week_name = get_week_name(start)

    ch_names = {
        "初級": f"{week_name}-初級",
        "中級": f"{week_name}-中級"
    }

    channels = {}
    for level, ch_name in ch_names.items():
        existing = discord.utils.get(guild.text_channels, name=ch_name)
        if existing:
            channels[level] = existing
        else:
            category = category_beginner if level == "初級" else category_intermediate
            new_ch = await guild.create_text_channel(ch_name, category=category)
            channels[level] = new_ch

    week = generate_week_schedule()
    for level, ch in channels.items():
        for date in week:
            embed = discord.Embed(title=f"📅 {level} - 三週間後の予定 {date}")
            for lbl in ["参加(🟢)", "オンライン可(🟡)", "不可(🔴)"]:
                embed.add_field(name=lbl, value="なし", inline=False)

            msg = await ch.send(embed=embed, view=VoteView(date, None))

            vote_data[str(msg.id)] = {
                "level": level,
                "dates": {date: {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}}
            }
            save_votes()

    print("✅ Step1: 初級・中級チャンネルへ三週間後スケジュール投稿完了。")

# ====== Step2: 二週間前リマインド ======
async def send_step2_remind():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start()
    week_name = get_week_name(start)

    for level in ["初級", "中級"]:
        ch_name = f"{week_name}-{level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_channel:
            print(f"⚠️ {ch_name} チャンネルが見つかりません。")
            continue

        msg_lines = [f"📢【{week_name} {level}リマインド】", "📅 日程ごとの参加状況："]

        # vote_dataのうち該当レベルのみ
        for message_id, info in vote_data.items():
            if info.get("level") != level:
                continue
            for date, status_dict in info["dates"].items():
                msg_lines.append(f"\n{date}")
                for s_label in ["参加(🟢)", "オンライン可(🟡)", "不可(🔴)"]:
                    users = status_dict.get(s_label, [])
                    msg_lines.append(f"{s_label} {' '.join(users) if users else 'なし'}")

        msg_text = "\n".join(msg_lines)
        await target_channel.send(msg_text)

    print("✅ Step2: 二週間前リマインド送信完了。")

# ====== Scheduler設定（テスト用） ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    print(f"✅ ログイン完了: {bot.user}")

    now = datetime.datetime.now(JST)
    # ===== テスト時刻設定 =====
    step1_time = now.replace(hour=14, minute=26, second=0, microsecond=0)
    step2_time = now.replace(hour=14, minute=28, second=0, microsecond=0)

    # 過ぎていたらスキップ
    if step1_time > now:
        scheduler.add_job(send_step1_schedule, DateTrigger(run_date=step1_time))
    if step2_time > now:
        scheduler.add_job(send_step2_remind, DateTrigger(run_date=step2_time))

    scheduler.start()

# ====== Bot起動 ======
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
load_votes()
bot.run(TOKEN)
