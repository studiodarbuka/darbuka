# bot.py
import os
import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import datetime
import pytz
import json
import asyncio

# ====== 基本設定 ======
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN を設定してください。")

JST = pytz.timezone("Asia/Tokyo")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== 永続保存ディレクトリ & ファイル ======
DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)
VOTE_FILE = os.path.join(DATA_DIR, "votes.json")
LOC_FILE = os.path.join(DATA_DIR, "locations.json")
CONFIRMED_FILE = os.path.join(DATA_DIR, "confirmed.json")

# ====== 永続データロード/セーブ ======
vote_data = {}   # runtime: { message_id: {"channel": channel_id, "YYYY-MM-DD (...)" : { "参加(🟢)": {...}, ... } } }
locations = {}   # runtime: { "初級": ["池袋A", ...], "中級": [...] }
confirmed = {}   # runtime: list/dict of confirmed events

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f"⚠ load_json error {path}: {e}")
        return default

def save_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠ save_json error {path}: {e}")

def load_votes():
    global vote_data
    vote_data = load_json(VOTE_FILE, {})

def save_votes():
    save_json(VOTE_FILE, vote_data)

def load_locations():
    global locations
    locations = load_json(LOC_FILE, {})
    return locations

def save_locations():
    save_json(LOC_FILE, locations)

def load_confirmed():
    global confirmed
    confirmed = load_json(CONFIRMED_FILE, {})
    return confirmed

def save_confirmed():
    save_json(CONFIRMED_FILE, confirmed)

# 初期ロード
load_votes()
load_locations()
load_confirmed()

# ====== 日付計算 ======
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

# ====== VoteView: 投票ボタン UI ======
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
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            pass

        participants = vote_data[message_id][self.date_str]["参加(🟢)"]
        if len(participants) >= 1:
            key = f"{message_id}|{self.date_str}"
            if confirmed.get(key) is None:
                confirmed[key] = {"notified": True, "level_guess": None, "participants": list(participants.values())}
                save_confirmed()
                channel = interaction.channel
                level = "初級" if "初級" in channel.name else ("中級" if "中級" in channel.name else "未特定")
                await send_confirm_notice(interaction.guild, level, self.date_str, list(participants.values()), key)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")


# ====== Step4 ConfirmView / Modal / Dropdown (画像添付対応) ======
class ConfirmView(discord.ui.View):
    def __init__(self, level, date_str, notice_key=None):
        super().__init__(timeout=None)
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key
        locs = load_locations().get(self.level, [])
        if locs:
            self.add_item(ConfirmDropdownView(level, date_str, notice_key, locs))

    @discord.ui.button(label="⚠️ 不確定にする", style=discord.ButtonStyle.danger)
    async def unconfirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="講師")
        if role and role not in interaction.user.roles:
            await interaction.response.send_message("⚠️ この操作は講師のみ可能です。", ephemeral=True)
            return

        target_ch = discord.utils.find(lambda c: self.level in c.name, interaction.guild.text_channels)
        embed = discord.Embed(
            title="⚠️【開催不確定】",
            description=f"{self.level} の {self.date_str} 開催は不確定です。ご迷惑をおかけしました。",
            color=0xFF4500
        )
        if target_ch:
            await target_ch.send(embed=embed)
        try:
            await interaction.response.edit_message(content="⚠️ 不確定が選ばれました。", view=None)
        except Exception:
            await interaction.response.send_message("⚠️ 不確定メッセージを送信しました。", ephemeral=True)
        if self.notice_key:
            confirmed[self.notice_key].update({
                "final": "不確定",
                "studio": None,
                "confirmed_by": interaction.user.display_name,
                "timestamp": datetime.datetime.now(JST).isoformat()
            })
            save_confirmed()

class ConfirmDropdownView(discord.ui.View):
    def __init__(self, level, date_str, notice_key=None, locations_list=None):
        super().__init__(timeout=None)
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key
        options = [discord.SelectOption(label=loc) for loc in locations_list]
        self.add_item(ConfirmDropdown(level, date_str, notice_key, options))

class ConfirmDropdown(discord.ui.Select):
    def __init__(self, level, date_str, notice_key, options):
        super().__init__(placeholder="スタジオを選択してください", options=options)
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key

    async def callback(self, interaction: discord.Interaction):
        studio_selected = self.values[0]
        modal = ConfirmModal(level=self.level, date_str=self.date_str, notice_key=self.notice_key, studio_default=studio_selected)
        await interaction.response.send_modal(modal)

class ConfirmModal(discord.ui.Modal, title="開催確定情報入力"):
    studio = discord.ui.TextInput(label="スタジオ名", required=True)
    image_url = discord.ui.TextInput(label="画像URL（任意）", required=False, placeholder="https://...")

    def __init__(self, level, date_str, notice_key=None, studio_default=None):
        super().__init__()
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key
        if studio_default:
            self.studio.default = studio_default

    async def on_submit(self, interaction: discord.Interaction):
        studio_name = self.studio.value
        img_url = self.image_url.value.strip() if self.image_url.value else None

        target_ch = discord.utils.find(lambda c: self.level in c.name, interaction.guild.text_channels)
        embed = discord.Embed(
            title="✅【開催確定】",
            description=f"{self.level} の {self.date_str} は **{studio_name}** で開催確定しました。",
            color=0x00FF00
        )
        if img_url:
            embed.set_image(url=img_url)

        files = [f for f in interaction.message.attachments] if interaction.message else []

        if target_ch:
            await target_ch.send(embed=embed, files=files)

        if self.notice_key:
            confirmed[self.notice_key].update({
                "final": "確定",
                "studio": studio_name,
                "image_url": img_url,
                "confirmed_by": interaction.user.display_name,
                "timestamp": datetime.datetime.now(JST).isoformat()
            })
            save_confirmed()

        await interaction.response.send_message(f"✅ {studio_name} を選択しました。", ephemeral=True)

async def send_confirm_notice(guild: discord.Guild, level: str, date_str: str, participants: list, notice_key: str = None):
    confirm_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
    if not confirm_channel:
        print("⚠️ 『人数確定通知所』チャンネルが見つかりません。")
        return

    role = discord.utils.get(guild.roles, name="講師")
    mention = role.mention if role else "@講師"
    participants_list = ", ".join(participants) if participants else "なし"

    embed = discord.Embed(
        title="📢 人数確定通知",
        description=(f"日程: {date_str}\n"
                     f"級: {level}\n"
                     f"参加者 ({len(participants)}人): {participants_list}\n\n"
                     f"{mention} さん、スタジオを抑えてください。\n"
                     f"開催の確定／不確定を下のボタンで選択してください。"),
        color=0x00BFFF
    )
    view = ConfirmView(level, date_str, notice_key)
    await confirm_channel.send(embed=embed, view=view)

# ====== BOT 起動 ======
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await tree.sync()
        print("✅ Slash commands synced!")
    except Exception as e:
        print(f"⚠ コマンド同期エラー: {e}")

# ====== /vote コマンド例 ======
@tree.command(name="vote", description="候補日投票用メッセージを作成")
@app_commands.describe(level="初級 or 中級")
async def vote(interaction: discord.Interaction, level: str):
    week_schedule = generate_week_schedule()
    for date_str in week_schedule:
        embed = discord.Embed(title=f"【予定候補】{date_str}", description=f"{level} の予定を投票してください。", color=0x00BFFF)
        view = VoteView(date_str)
        await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ 候補日投票を作成しました。", ephemeral=True)

bot.run(TOKEN)
