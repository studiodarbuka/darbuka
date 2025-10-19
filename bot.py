import os
import discord
from discord.ext import commands
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import asyncio

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

# ====== 日本語曜日で一週間生成 ======
def generate_week_schedule():
    start = get_schedule_start()
    weekday_jp = ["月","火","水","木","金","土","日"]
    return [
        f"{(start + datetime.timedelta(days=i)).strftime('%Y-%m-%d')} ({weekday_jp[(start + datetime.timedelta(days=i)).weekday()]})"
        for i in range(7)
    ]

# ====== 月第N週の文字列を返す ======
def get_week_name(date):
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    return f"{month}月第{week_number}週"

# ====== 投票ボタン付きビュー（トグル式 + Step4通知対応） ======
class VoteView(discord.ui.View):
    def __init__(self, date_str, level):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.level = level  # 初級 or 中級

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}

        # トグル式：同じボタンを押したら無効化
        current_status = None
        for k, v in vote_data[message_id][self.date_str].items():
            if user_id in v:
                current_status = k
                break

        if current_status == status:
            del vote_data[message_id][self.date_str][status][user_id]
        else:
            for v_list in vote_data[message_id][self.date_str].values():
                v_list.pop(user_id, None)
            vote_data[message_id][self.date_str][status][user_id] = user_name

        save_votes()

        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v.values()) if v else "0人", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        # Step4: 参加者3人以上で通知
        if len(vote_data[message_id][self.date_str]["参加(🟢)"]) >= 3:
            await send_step4_notification(self.date_str, self.level, vote_data[message_id][self.date_str]["参加(🟢)"])

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step4 確定/不確定通知 ======
class ConfirmView(discord.ui.View):
    def __init__(self, date_str, level, participants, target_channel):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.level = level
        self.participants = participants
        self.target_channel = target_channel

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.target_channel.send(f"✅ 【{self.level} 確定】 {self.date_str} は確定しました！参加者: {', '.join(self.participants)}")
        await interaction.response.send_message("講師に確定通知を送信しました。", ephemeral=True)

    @discord.ui.button(label="不確定", style=discord.ButtonStyle.danger)
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.target_channel.send(f"❌ 【{self.level} 不確定】 {self.date_str} は確定できませんでした。申し訳ありません。")
        await interaction.response.send_message("講師に不確定通知を送信しました。", ephemeral=True)

async def send_step4_notification(date_str, level, participants_dict):
    guild = bot.guilds[0]
    notification_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
    if not notification_channel:
        print("⚠ チャンネル「人数確定通知所」が見つかりません")
        return

    participants = list(participants_dict.values())
    msg = await notification_channel.send(
        f"📢【{level}】{date_str} 参加人数が3人以上になりました！\n参加者: {', '.join(participants)}\nスタジオを抑えてください。",
        view=ConfirmView(date_str, level, participants, notification_channel)
    )
    print(f"✅ Step4: {level} {date_str} 参加者3人以上通知送信完了")

# ====== Step1～3 実装（前と同様） ======
# send_step1_schedule, send_step2_remind, send_step3_remind
# （Step3で全員投票済みなら感謝メッセージ表示済み）

scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    print(f"✅ ログイン完了: {bot.user}")

    loop = asyncio.get_running_loop()
    now = datetime.datetime.now(JST)
    step1_time = now.replace(hour=23, minute=17, second=0, microsecond=0)
    step2_time = now.replace(hour=23, minute=18, second=0, microsecond=0)
    step3_time = now.replace(hour=23, minute=18, second=30, microsecond=0)

    def schedule_coroutine(coro_func):
        asyncio.run_coroutine_threadsafe(coro_func(), loop)

    if step1_time > now:
        scheduler.add_job(lambda: schedule_coroutine(send_step1_schedule), DateTrigger(run_date=step1_time))
    if step2_time > now:
        scheduler.add_job(lambda: schedule_coroutine(send_step2_remind), DateTrigger(run_date=step2_time))
    if step3_time > now:
        scheduler.add_job(lambda: schedule_coroutine(send_step3_remind), DateTrigger(run_date=step3_time))

    scheduler.start()
    print("⏱ Step1～Step3 ジョブをスケジュール登録完了")

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
