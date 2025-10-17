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

# ====== 日曜始まり3週間後の週を計算 ======
def get_schedule_start():
    today = datetime.datetime.now(JST)
    # 「今週の日曜」を見つける（今日を含めず）
    days_since_sunday = (today.weekday() + 1) % 7  # 月=0 → 日=6
    this_sunday = today - datetime.timedelta(days=days_since_sunday)
    # 今週を1週目として、3週間後の日曜を取得
    target = this_sunday + datetime.timedelta(weeks=3)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    return [(start + datetime.timedelta(days=i)).strftime("%Y-%m-%d (%a)") for i in range(7)]

# ====== ボタン形式投票 ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_name = interaction.user.display_name

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}

        # トグル形式
        for k, v in vote_data[message_id][self.date_str].items():
            if user_name in v:
                v.remove(user_name)
        vote_data[message_id][self.date_str][status].append(user_name)

        save_votes()

        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)

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

# ====== Step1: 三週間後のスケジュールを投稿 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
        return

    week = generate_week_schedule()
    for date in week:
        embed_title = f"📅 三週間後の予定 {date}"
        message_id_placeholder = f"tmp-{date}"
        vote_data[message_id_placeholder] = {date: {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}}
        save_votes()

        embed = discord.Embed(title=embed_title)
        for k, v in vote_data[message_id_placeholder][date].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="0人", inline=False)

        view = VoteView(date)
        msg = await channel.send(embed=embed, view=view)
        vote_data[str(msg.id)] = vote_data.pop(message_id_placeholder)
        save_votes()

    print("✅ Step1: 三週間後スケジュール投稿完了。")

# ====== テスト用スケジュール（即実行） ======
@bot.event
async def on_ready():
    print(f"✅ ログイン完了: {bot.user}")
    scheduler = AsyncIOScheduler(timezone=JST)
    now = datetime.datetime.now(JST) + datetime.timedelta(seconds=5)
    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=now))
    scheduler.start()

# ====== 起動 ======
load_votes()
bot.run(os.getenv("DISCORD_BOT_TOKEN"))
