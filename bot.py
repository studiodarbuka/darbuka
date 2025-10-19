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

# ====== Step4 確定・不確定ボタンビュー ======
class ConfirmView(discord.ui.View):
    def __init__(self, date_str, level, participants):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.level = level
        self.participants = participants

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        ch_name = f"{get_week_name(get_schedule_start())}-{self.level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if target_channel:
            await target_channel.send(f"📢【確定通知】{self.level}級、{self.date_str}、参加者: {', '.join(self.participants)} で確定しました。")
        await interaction.response.send_message("✅ 確定通知を送信しました。", ephemeral=True)

    @discord.ui.button(label="不確定", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        ch_name = f"{get_week_name(get_schedule_start())}-{self.level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if target_channel:
            await target_channel.send(f"⚠【不確定通知】申し訳ありません。{self.level}級、{self.date_str}、参加者: {', '.join(self.participants)} は確定できませんでした。")
        await interaction.response.send_message("❌ 不確定通知を送信しました。", ephemeral=True)

# ====== 投票ボタン付きビュー（トグル式、user_id管理） ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str
        self.level = None  # 後で設定

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        # レベルを取得（初級/中級）
        if not self.level:
            self.level = "初級" if "初級" in interaction.channel.name else "中級"

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}

        # トグル式処理
        current_status = None
        for k, v in vote_data[message_id][self.date_str].items():
            if user_id in v:
                current_status = k
                break

        if current_status == status:
            del vote_data[message_id][self.date_str][status][user_id]
        else:
            for v_dict in vote_data[message_id][self.date_str].values():
                if user_id in v_dict:
                    del v_dict[user_id]
            vote_data[message_id][self.date_str][status][user_id] = user_name

        save_votes()

        # Embed更新
        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v.values()) if v else "0人", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        # ===== Step4 テスト用通知 (参加者1人以上で通知) =====
        if status == "参加(🟢)":
            current_participants = list(vote_data[message_id][self.date_str]["参加(🟢)"].values())
            if len(current_participants) >= 1:  # ←テスト用: 1人以上
                guild = interaction.guild
                notify_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
                role_lecturer = discord.utils.get(guild.roles, name="講師")
                if notify_channel and role_lecturer:
                    view = ConfirmView(self.date_str, self.level, current_participants)
                    await notify_channel.send(
                        content=f"{role_lecturer.mention}\n📢 {self.date_str}、{self.level}級の参加人数が1人以上になりました（テスト用）。\n参加者: {', '.join(current_participants)}\nスタジオを抑えてください。",
                        view=view
                    )

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Step1 / Step2 / Step3 関数 ======
# （省略：先ほどのStep1～Step3と同じ内容をここに入れる）

# ====== Scheduler ======
scheduler = AsyncIOScheduler(timezone=JST)

@bot.event
async def on_ready():
    load_votes()
    print(f"✅ ログイン完了: {bot.user}")

    now = datetime.datetime.now(JST)
    step1_time = now.replace(hour=22, minute=20, second=0, microsecond=0)
    step2_time = now.replace(hour=16, minute=21, second=0, microsecond=0)
    step3_time = now.replace(hour=16, minute=22, second=0, microsecond=0)

    if step1_time > now:
        scheduler.add_job(send_step1_schedule, DateTrigger(run_date=step1_time))
    if step2_time > now:
        scheduler.add_job(send_step2_remind, DateTrigger(run_date=step2_time))
    if step3_time > now:
        scheduler.add_job(send_step3_remind, DateTrigger(run_date=step3_time))

    scheduler.start()

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
