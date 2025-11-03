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
vote_data = {}
locations = {}
confirmed = {}

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

        # トグル式
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
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            pass

        # 自動通知 — 参加が1人以上で初回のみ
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

# ====== Confirm / Studio UI (Step4) + 画像対応 ======
class ConfirmView(discord.ui.View):
    def __init__(self, level, date_str, notice_key=None):
        super().__init__(timeout=None)
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key

    @discord.ui.button(label="✅ 開催を確定する", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="講師")
        if role and role not in interaction.user.roles:
            await interaction.response.send_message("⚠️ この操作は講師のみ可能です。", ephemeral=True)
            return

        locs = load_locations().get(self.level, [])
        if not locs:
            await interaction.response.send_message(f"⚠️ {self.level} のスタジオが未登録です。`/place 登録` で追加してください。", ephemeral=True)
            return

        view = StudioSelectView(self.level, self.date_str, locs, self.notice_key)
        await interaction.response.send_message("スタジオを選択してください（このメッセージは秘密扱いです）", view=view, ephemeral=True)

class StudioSelectView(discord.ui.View):
    def __init__(self, level, date_str, locations_list, notice_key=None):
        super().__init__(timeout=60)
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key
        options = [discord.SelectOption(label=loc, description=f"{level}用スタジオ") for loc in locations_list]
        self.add_item(StudioDropdown(level, date_str, options, notice_key))

class StudioDropdown(discord.ui.Select):
    def __init__(self, level, date_str, options, notice_key=None):
        super().__init__(placeholder="スタジオを選択してください", options=options, min_values=1, max_values=1)
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key

    async def callback(self, interaction: discord.Interaction):
        studio = self.values[0]
        attachments = [f.url for f in interaction.message.attachments] if interaction.message.attachments else []
        embed = discord.Embed(
            title="✅【開催確定】",
            description=f"{self.level} の {self.date_str} は **{studio}** で開催が確定しました。参加者の皆さん、よろしくお願いします！",
            color=0x00FF00
        )
        if attachments:
            embed.set_image(url=attachments[0])

        target_ch = discord.utils.find(lambda c: self.level in c.name, interaction.guild.text_channels)
        if target_ch:
            await target_ch.send(embed=embed)

        try:
            await interaction.response.edit_message(content=f"✅ {studio} を選択しました。", view=None)
        except Exception:
            await interaction.response.send_message(f"✅ {studio} を選択しました。", ephemeral=True)

        if self.notice_key:
            confirmed[self.notice_key].update({"final": "確定", "studio": studio, "confirmed_by": interaction.user.display_name, "timestamp": datetime.datetime.now(JST).isoformat(), "attachments": attachments})
            save_confirmed()

# ====== send_confirm_notice helper ======
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
        description=(
            f"日程: {date_str}\n"
            f"級: {level}\n"
            f"参加者 ({len(participants)}人): {participants_list}\n\n"
            f"{mention} さん、スタジオを抑えてください。\n"
            f"開催の確定を下のボタンで選択してください。"
        ),
        color=0x00BFFF
    )
    view = ConfirmView(level, date_str, notice_key)
    await confirm_channel.send(embed=embed, view=view)

# ====== Step1～3 実装（時間指定テスト用） ======
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

    ch_names = {"初級": f"{week_name}-初級", "中級": f"{week_name}-中級"}
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
            embed.add_field(name="参加(🟢)", value="0人", inline=False)
            embed.add_field(name="オンライン可(🟡)", value="0人", inline=False)
            embed.add_field(name="不可(🔴)", value="0人", inline=False)
            view = VoteView(date)
            msg = await ch.send(embed=embed, view=view)
            vote_data[str(msg.id)] = {"channel": ch.id, date: {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}}
            save_votes()
    print("✅ Step1: 投稿完了")

async def send_step2_remind():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start()
    week_name = get_week_name(start)

    for level in ["初級", "中級"]:
        ch_name = f"{week_name}-{level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_channel:
            continue

        week = generate_week_schedule()
        message = f"📢【{week_name} {level}リマインド】\n\n📅 日程ごとの参加状況：\n\n"
        for date in week:
            for msg_id, data in vote_data.items():
                if data.get("channel") != target_channel.id or date not in data:
                    continue
                date_votes = data[date]
                message += f"{date}\n"
                message += f"参加(🟢) " + (", ".join(date_votes["参加(🟢)"].values()) if date_votes["参加(🟢)"] else "なし") + "\n"
                message += f"オンライン可(🟡) " + (", ".join(date_votes["オンライン可(🟡)"].values()) if date_votes["オンライン可(🟡)"] else "なし") + "\n"
                message += f"不可(🔴) " + (", ".join(date_votes["不可(🔴)"].values()) if date_votes["不可(🔴)"] else "なし") + "\n\n"
        await target_channel.send(message)
    print("✅ Step2: テストリマインド送信完了")

async def send_step3_remind():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start()
    week_name = get_week_name(start)

    for level in ["初級", "中級"]:
        ch_name = f"{week_name}-{level}"
        target_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if not target_channel:
            continue

        role = discord.utils.get(guild.roles, name=level)
        if not role:
            continue

        week = generate_week_schedule()
        message = f"📢【{week_name} {level} 1週間前催促】\n\n"

        all_voted = True
        for date in week:
            for msg_id, data in vote_data.items():
                if data.get("channel") != target_channel.id or date not in data:
                    continue
                date_votes = data[date]

                unvoted_members = []
                for member in role.members:
                    voted_ids = set()
                    for v_dict in date_votes.values():
                        voted_ids.update(v_dict.keys())
                    if str(member.id) not in voted_ids:
                        unvoted_members.append(member.mention)

                if unvoted_members:
                    all_voted = False
                    message += f"{date}\n" + ", ".join(unvoted_members) + "\n\n"

        if all_voted:
            message += "全員投票済みです。"
        await target_channel.send(message)
    print("✅ Step3: 1週間前催促送信完了")

# ====== Scheduler 設定 ======
scheduler = AsyncIOScheduler()

@bot.event
async def on_ready():
    load_votes()
    load_locations()
    load_confirmed()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠ コマンド同期エラー: {e}")

    now = datetime.datetime.now(JST)

    # ===== テスト用：任意時間に Step1～3 実行 =====
    three_week_test = now.replace(hour=22, minute=51, second=0, microsecond=0)  # Step1
    two_week_test   = now.replace(hour=22, minute=52, second=0, microsecond=0)  # Step2
    one_week_test   = now.replace(hour=22, minute=53, second=0, microsecond=0)  # Step3

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))
    scheduler.add_job(send_step2_remind,   DateTrigger(run_date=two_week_test))
    scheduler.add_job(send_step3_remind,   DateTrigger(run_date=one_week_test))

    scheduler.start()
    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started. Step1～3 は指定時刻に実行されます。")

# ====== Bot起動 ======
if __name__ == "__main__":
    bot.run(TOKEN)
