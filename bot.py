import os
import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import datetime
import pytz
import json

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== 永続保存 ======
PERSISTENT_DIR = "./data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "votes.json")
LOCATION_FILE = os.path.join(PERSISTENT_DIR, "locations.json")

vote_data = {}
locations = []

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

def load_locations():
    global locations
    if os.path.exists(LOCATION_FILE):
        with open(LOCATION_FILE, "r", encoding="utf-8") as f:
            locations = json.load(f)
    else:
        locations = []

def save_locations():
    with open(LOCATION_FILE, "w", encoding="utf-8") as f:
        json.dump(locations, f, ensure_ascii=False, indent=2)

# ====== タイムゾーン・日付計算 ======
JST = pytz.timezone("Asia/Tokyo")

def get_schedule_start():
    today = datetime.datetime.now(JST)
    days_since_sunday = (today.weekday() + 1) % 7
    this_sunday = today - datetime.timedelta(days=days_since_sunday)
    target = this_sunday + datetime.timedelta(weeks=3)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)

def generate_week_schedule():
    start = get_schedule_start()
    weekday_jp = ["月","火","水","木","金","土","日"]
    return [
        f"{(start + datetime.timedelta(days=i)).strftime('%Y-%m-%d')} ({weekday_jp[(start + datetime.timedelta(days=i)).weekday()]})"
        for i in range(7)
    ]

def get_week_name(date):
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    return f"{month}月第{week_number}週"

# ====== VoteView / ConfirmView ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}

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

        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v.values()) if v else "0人", inline=False)
        await interaction.response.edit_message(embed=embed, view=self)

        participants = vote_data[message_id][self.date_str]["参加(🟢)"]
        if len(participants) >= 1:
            await self.send_confirm_notice(interaction, participants)

    async def send_confirm_notice(self, interaction: discord.Interaction, participants: dict):
        guild = interaction.guild
        confirm_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
        if not confirm_channel:
            print("⚠️ 『人数確定通知所』チャンネルが見つかりません。")
            return

        role = discord.utils.get(guild.roles, name="講師")
        mention_str = role.mention if role else "@講師"

        level = "初級" if "初級" in interaction.channel.name else "中級"
        participants_list = ", ".join(participants.values())

        view = ConfirmView(level, self.date_str)
        embed = discord.Embed(
            title="📢 人数確定通知",
            description=(
                f"日程: {self.date_str}\n"
                f"級: {level}\n"
                f"参加者 ({len(participants)}人): {participants_list}\n\n"
                f"{mention_str} さん、スタジオを抑えてください。"
            ),
            color=0x00BFFF
        )
        await confirm_channel.send(embed=embed, view=view)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

class ConfirmView(discord.ui.View):
    def __init__(self, level, date_str):
        super().__init__(timeout=None)
        self.level = level
        self.date_str = date_str

    @discord.ui.button(label="✅ 開催確定", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not locations:
            await interaction.response.send_message("⚠️ スタジオが登録されていません。/場所 登録で追加してください。", ephemeral=True)
            return
        options = [discord.SelectOption(label=loc) for loc in locations]
        select = discord.ui.Select(placeholder="スタジオを選択", options=options)

        async def select_callback(select_interaction: discord.Interaction):
            chosen = select_interaction.data["values"][0]
            target_ch = discord.utils.find(lambda c: self.level in c.name, interaction.guild.text_channels)
            if target_ch:
                await target_ch.send(f"✅【開催確定】\n{self.level}の{self.date_str}開催は確定です。\nスタジオ: {chosen}")
                await select_interaction.response.send_message("✅ 確定通知を送信しました。", ephemeral=True)

        select.callback = select_callback
        temp_view = discord.ui.View()
        temp_view.add_item(select)
        await interaction.response.send_message("スタジオを選択してください。", view=temp_view, ephemeral=True)

    @discord.ui.button(label="⚠ 不確定", style=discord.ButtonStyle.danger)
    async def unconfirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        target_ch = discord.utils.find(lambda c: self.level in c.name, interaction.guild.text_channels)
        if target_ch:
            await target_ch.send(f"⚠️【開催不確定】\n{self.level}の{self.date_str}開催は不確定です。ご迷惑をおかけしました。")
            await interaction.response.send_message("✅ 不確定通知を送信しました。", ephemeral=True)

# ====== Scheduler 初期化 ======
scheduler = AsyncIOScheduler(timezone=JST)

# ====== Step1～3関数 ======
# （省略しません、先ほどと同じ内容）
# ... send_step1_schedule / send_step2_remind / send_step3_remind ...

# ====== /場所 コマンド ======
@tree.command(name="場所", description="スタジオを登録・削除・一覧表示")
@app_commands.describe(
    action="登録 / 削除 / 一覧",
    スタジオ名="例: スタジオA（登録・削除時）"
)
async def location_command(interaction: discord.Interaction, action: str, スタジオ名: str = None):
    action = action.lower()
    load_locations()
    if action == "登録":
        if スタジオ名 and スタジオ名 not in locations:
            locations.append(スタジオ名)
            save_locations()
            await interaction.response.send_message(f"✅ '{スタジオ名}' を登録しました。", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 有効なスタジオ名を指定してください。", ephemeral=True)
    elif action == "削除":
        if スタジオ名 and スタジオ名 in locations:
            locations.remove(スタジオ名)
            save_locations()
            await interaction.response.send_message(f"✅ '{スタジオ名}' を削除しました。", ephemeral=True)
        else:
            await interaction.response.send_message("⚠️ 指定したスタジオは登録されていません。", ephemeral=True)
    elif action == "一覧":
        if locations:
            await interaction.response.send_message("📋 登録スタジオ一覧:\n" + "\n".join(locations), ephemeral=True)
        else:
            await interaction.response.send_message("📋 登録スタジオはありません。", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ action は登録 / 削除 / 一覧 のいずれかです。", ephemeral=True)

# ====== /確定 / 不確定 コマンド ======
@tree.command(name="確定", description="指定した級の開催を確定として通知")
@app_commands.describe(級="初級 or 中級", 日付="例: 2025-11-09")
async def confirm_event(interaction: discord.Interaction, 級: str, 日付: str):
    guild = interaction.guild
    target_ch = discord.utils.find(lambda c: 級 in c.name, guild.text_channels)
    if target_ch:
        await target_ch.send(f"✅【開催確定】\n{級}の{日付}開催は確定です。参加者の皆さん、よろしくお願いします！")
        await interaction.response.send_message("✅ 確定通知を送信しました。", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 対象チャンネルが見つかりません。", ephemeral=True)

@tree.command(name="不確定", description="指定した級の開催を不確定として通知")
@app_commands.describe(級="初級 or 中級", 日付="例: 2025-11-09")
async def unconfirm_event(interaction: discord.Interaction, 級: str, 日付: str):
    guild = interaction.guild
    target_ch = discord.utils.find(lambda c: 級 in c.name, guild.text_channels)
    if target_ch:
        await target_ch.send(f"⚠️【開催不確定】\n{級}の{日付}開催は不確定です。ご迷惑をおかけしました。")
        await interaction.response.send_message("✅ 不確定通知を送信しました。", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ 対象チャンネルが見つかりません。", ephemeral=True)

# ====== /event 突発イベント ======
@tree.command(name="event", description="突発イベントを作成して投票可能")
@app_commands.describe(級="初級 or 中級", 日付="例: 2025-11-09", タイトル="イベントタイトル")
async def create_event(interaction: discord.Interaction, 級: str, 日付: str, タイトル: str):
    guild = interaction.guild
    target_ch = discord.utils.find(lambda c: 級 in c.name, guild.text_channels)
    if not target_ch:
        await interaction.response.send_message("⚠️ 対象チャンネルが見つかりません。", ephemeral=True)
        return

    embed = discord.Embed(title=f"📅 {級} - 突発イベント {日付}", description=タイトル)
    embed.add_field(name="参加(🟢)", value="0人", inline=False)
    embed.add_field(name="オンライン可(🟡)", value="0人", inline=False)
    embed.add_field(name="不可(🔴)", value="0人", inline=False)

    view = VoteView(日付)
    msg = await target_ch.send(embed=embed, view=view)
    vote_data[str(msg.id)] = {"channel": target_ch.id, 日付: {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}}
    save_votes()
    await interaction.response.send_message("✅ 突発イベントを作成しました。", ephemeral=True)

# ====== on_ready ======
@bot.event
async def on_ready():
    load_votes()
    load_locations()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠ コマンド同期エラー: {e}")

    now = datetime.datetime.now(JST)
    # ===== 固定時刻スケジュール（テスト用） =====
    three_week_test = now.replace(hour=2, minute=10, second=0, microsecond=0)  # Step1
    two_week_test   = now.replace(hour=2, minute=11, second=0, microsecond=0)  # Step2
    one_week_test   = now.replace(hour=2, minute=12, second=0, microsecond=0)  # Step3

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))
    scheduler.add_job(send_step2_remind,   DateTrigger(run_date=two_week_test))
    scheduler.add_job(send_step3_remind,   DateTrigger(run_date=one_week_test))

    scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print(f"✅ Scheduler started (Test mode). Step1～3は指定時刻に実行されます。")

# ====== Bot 起動 ======
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
bot.run(TOKEN)
