# bot.py (Render-ready, merged full)
# - 古いチャンネル自動生成ロジックを復元
# - APScheduler の coroutine ジョブ登録で "no running event loop" を回避
# - Render Worker 向けに常時稼働する構成

import os
import logging
import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import datetime
import pytz
import json
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# ====== データディレクトリ & ファイル ======
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
        logger.warning(f"⚠ load_json error {path}: {e}")
        return default


def save_json(path, obj):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"⚠ save_json error {path}: {e}")


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
    # date は datetime
    month = date.month
    first_day = date.replace(day=1)
    first_sunday = first_day + datetime.timedelta(days=(6 - first_day.weekday()) % 7)
    week_number = ((date - first_sunday).days // 7) + 1
    # 例: 12月第2週
    return f"{month}月第{week_number}週"

# ====== VoteView UI ======
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def handle_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)
        user_name = interaction.user.display_name

        vote_data.setdefault(message_id, {})
        vote_data[message_id].setdefault(self.date_str, {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}})

        current_status = None
        for k, v in vote_data[message_id][self.date_str].items():
            if user_id in v:
                current_status = k
                break
        if current_status == status:
            del vote_data[message_id][self.date_str][status][user_id]
        else:
            for v_dict in vote_data[message_id][self.date_str].values():
                v_dict.pop(user_id, None)
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
                channel_name = interaction.channel.name
                level = "初級" if "初級" in channel_name else ("中級" if "中級" in channel_name else "未特定")
                await send_confirm_notice(interaction.guild, level, self.date_str, list(participants.values()), key, source_channel_id=interaction.channel.id)

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.success)
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="オンライン可(🟡)", style=discord.ButtonStyle.primary)
    async def maybe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "オンライン可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.danger)
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_vote(interaction, "不可(🔴)")

# ====== Confirm / Studio selection ======
class ConfirmViewWithImage(discord.ui.View):
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

        await interaction.response.send_message(
            "📸 このメッセージに画像を添付して送信してください。\n送らない場合は「スキップ」と返信してください。",
            ephemeral=True
        )

        def check(msg):
            return msg.author == interaction.user and msg.channel == interaction.channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=300)
            if msg.content.lower() == "スキップ":
                image_url = None
            elif msg.attachments:
                image_url = msg.attachments[0].url
            else:
                image_url = None
        except asyncio.TimeoutError:
            image_url = None
            await interaction.channel.send("⏰ 画像送信タイムアウト。スキップ扱いにします。")

        if self.notice_key:
            confirmed.setdefault(self.notice_key, {})
            confirmed[self.notice_key]["image_url"] = image_url
            save_confirmed()

        locs = load_locations().get("共通", [])
        if not locs:
            await interaction.channel.send("⚠️ スタジオが未登録です。/place 登録 <名前> で追加してください。")
            return

        view = StudioSelectView(self.date_str, locs, self.notice_key)
        await interaction.channel.send("🏢 スタジオを選択してください", view=view)


class StudioSelectView(discord.ui.View):
    def __init__(self, date_str, locations_list, notice_key=None):
        super().__init__(timeout=300)
        self.date_str = date_str
        self.notice_key = notice_key
        options = [discord.SelectOption(label=loc) for loc in locations_list]
        self.add_item(StudioDropdown(date_str, options, notice_key))


class StudioDropdown(discord.ui.Select):
    def __init__(self, date_str, options, notice_key=None):
        super().__init__(placeholder="スタジオを選択してください", options=options, min_values=1, max_values=1)
        self.date_str = date_str
        self.notice_key = notice_key

    async def callback(self, interaction: discord.Interaction):
        studio = self.values[0]

        week_name = get_week_name(datetime.datetime.now(JST))
        if "初級" in interaction.channel.name:
            confirm_channel = discord.utils.get(interaction.guild.text_channels, name=f"{week_name}-初級")
        elif "中級" in interaction.channel.name:
            confirm_channel = discord.utils.get(interaction.guild.text_channels, name=f"{week_name}-中級")
        else:
            confirm_channel = discord.utils.get(interaction.guild.text_channels, name="人数確定通知所")

        embed = discord.Embed(
            title="✅【開催確定】",
            description=f"{self.date_str} は **{studio}** で開催が確定しました。\n参加者の皆さん、よろしくお願いします！",
            color=0x00FF00
        )

        if self.notice_key and confirmed.get(self.notice_key, {}).get("image_url"):
            embed.set_image(url=confirmed[self.notice_key]["image_url"])

        if confirm_channel:
            await confirm_channel.send(embed=embed)

        if self.notice_key:
            confirmed[self.notice_key].update({
                "final": "確定",
                "studio": studio,
                "confirmed_by": interaction.user.display_name,
                "timestamp": datetime.datetime.now(JST).isoformat()
            })
            save_confirmed()

        try:
            await interaction.response.edit_message(content=f"✅ {studio} を選択しました。", view=None)
        except Exception:
            await interaction.response.send_message(f"✅ {studio} を選択しました。", ephemeral=True)

# ====== send_confirm_notice helper ======
async def send_confirm_notice(guild: discord.Guild, level: str, date_str: str, participants: list, notice_key: str = None, source_channel_id: int = None):
    week_name = get_week_name(datetime.datetime.now(JST))
    if "初級" in level:
        confirm_channel = discord.utils.get(guild.text_channels, name=f"{week_name}-初級")
    elif "中級" in level:
        confirm_channel = discord.utils.get(guild.text_channels, name=f"{week_name}-中級")
    else:
        confirm_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")

    if not confirm_channel:
        logger.warning("⚠️ 確定通知送信先チャンネルが見つかりません。")
        return

    role = discord.utils.get(guild.roles, name="講師")
    mention = role.mention if role else "@講師"
    participants_list = ", ".join(participants) if participants else "なし"

    if notice_key:
        confirmed.setdefault(notice_key, {})
        confirmed[notice_key].update({"source_channel": source_channel_id})
        save_confirmed()

    embed = discord.Embed(
        title="📢 人数確定通知",
        description=(f"日程: {date_str}\n"
                     f"級: {level}\n"
                     f"参加者 ({len(participants)}人): {participants_list}\n\n"
                     f"{mention} さん、スタジオを抑えてください。\n"
                     f"開催の確定／不確定を下のボタンで選択してください。"),
        color=0x00BFFF
    )
    view = ConfirmViewWithImage(level, date_str, notice_key=notice_key)
    await confirm_channel.send(embed=embed, view=view)

# ====== Step1～3 ======
# Step1: チャンネル作成 & 投票ポスト
async def send_step1_schedule():
    await bot.wait_until_ready()
    if not bot.guilds:
        logger.warning("⚠️ Bot はどのギルドにも参加していません。")
        return
    guild = bot.guilds[0]

    # カテゴリ取得（必須）
    category_beginner = discord.utils.get(guild.categories, name="初級")
    category_intermediate = discord.utils.get(guild.categories, name="中級")
    if not category_beginner or not category_intermediate:
        logger.warning("⚠️ カテゴリ「初級」「中級」が見つかりません。")
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
            embed.add_field(name="参加(🟢)", value="0人", inline=False)
            embed.add_field(name="オンライン可(🟡)", value="0人", inline=False)
            embed.add_field(name="不可(🔴)", value="0人", inline=False)
            view = VoteView(date)
            msg = await ch.send(embed=embed, view=view)
            vote_data[str(msg.id)] = {"channel": ch.id, date: {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}}
    save_votes()
    logger.info("✅ Step1: 投稿完了")

# Step2: 2週間前リマインド
async def send_step2_remind():
    await bot.wait_until_ready()
    if not bot.guilds:
        return
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
                message += f"参加(🟢) " + (", ".join(date_votes["参加(🟢)"].values()) if date_votes["参加(🟢)" ] else "なし") + "\n"
                message += f"オンライン可(🟡) " + (", ".join(date_votes["オンライン可(🟡)"].values()) if date_votes["オンライン可(🟡)" ] else "なし") + "\n"
                message += f"不可(🔴) " + (", ".join(date_votes["不可(🔴)"].values()) if date_votes["不可(🔴)" ] else "なし") + "\n\n"
        if message.strip():
            await target_channel.send(message)
    logger.info("✅ Step2: リマインド送信完了")

# Step3: 1週間前催促
async def send_step3_remind():
    await bot.wait_until_ready()
    if not bot.guilds:
        return
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
            date_has_msg = False
            for msg_id, data in vote_data.items():
                if data.get("channel") != target_channel.id or date not in data:
                    continue
                date_has_msg = True
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
            if not date_has_msg:
                message += f"{date}\n投票メッセージなし\n\n"
        if not all_voted:
            await target_channel.send(message)
    logger.info("✅ Step3: 1週間前催促送信完了")

# ====== /place コマンド ======
@tree.command(name="place", description="スタジオを管理します（追加/削除/表示）")
@app_commands.describe(action="操作: 登録 / 削除 / 一覧", name="スタジオ名（登録/削除時に指定）")
async def manage_location(interaction: discord.Interaction, action: str, name: str = None):
    action = action.strip()
    load_locations()
    if action in ("登録", "削除") and (not name or name.strip() == ""):
        await interaction.response.send_message("⚠️ 登録・削除時は必ずスタジオ名を指定してください。", ephemeral=True)
        return
    if action == "登録":
        locations.setdefault("共通", [])
        if name in locations["共通"]:
            await interaction.response.send_message(f"⚠️ {name} は既に登録済みです。", ephemeral=True)
            return
        locations["共通"].append(name)
        save_locations()
        await interaction.response.send_message(f"✅ {name} を登録しました。", ephemeral=True)
    elif action == "削除":
        if name not in locations.get("共通", []):
            await interaction.response.send_message(f"⚠️ {name} は登録されていません。", ephemeral=True)
            return
        locations["共通"].remove(name)
        save_locations()
        await interaction.response.send_message(f"✅ {name} を削除しました。", ephemeral=True)
    elif action == "一覧":
        loc_list = "\n".join(locations.get("共通", [])) or "未登録"
        await interaction.response.send_message(f"📃 登録スタジオ一覧:\n{loc_list}", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ action は 登録 / 削除 / 一覧 のいずれかを指定してください。", ephemeral=True)

# ====== Scheduler 設定 ======
scheduler = AsyncIOScheduler(timezone=JST)

# wrapper coroutine（APScheduler に登録する coro）
async def schedule_step1():
    await send_step1_schedule()

async def schedule_step2():
    await send_step2_remind()

async def schedule_step3():
    await send_step3_remind()


@bot.event
async def on_ready():
    # reload persistence
    load_votes()
    load_locations()
    load_confirmed()

    try:
        await tree.sync()
        logger.info("✅ Slash Commands synced!")
    except Exception:
        logger.exception("⚠ コマンド同期エラー")

    now = datetime.datetime.now(JST)
    three_week_test = now.replace(hour=12, minute=0, second=0, microsecond=0)
    two_week_test   = now.replace(hour=12, minute=2, second=0, microsecond=0)
    one_week_test   = now.replace(hour=12, minute=6, second=0, microsecond=0)

    if three_week_test <= now: three_week_test += datetime.timedelta(days=1)
    if two_week_test   <= now: two_week_test   += datetime.timedelta(days=1)
    if one_week_test   <= now: one_week_test   += datetime.timedelta(days=1)

    # scheduler start if not running
    if not scheduler.running:
        scheduler.start()

    # remove duplicate jobs
    for jid in ("step1", "step2", "step3"):
        try:
            if scheduler.get_job(jid):
                scheduler.remove_job(jid)
        except Exception:
            pass

    # register coroutine jobs directly
    scheduler.add_job(schedule_step1, trigger=DateTrigger(run_date=three_week_test), id="step1")
    scheduler.add_job(schedule_step2, trigger=DateTrigger(run_date=two_week_test), id="step2")
    scheduler.add_job(schedule_step3, trigger=DateTrigger(run_date=one_week_test), id="step3")

    logger.info(f"✅ Logged in as {bot.user}")
    logger.info(f"✅ Scheduler started. Step1~3 scheduled at: {three_week_test}, {two_week_test}, {one_week_test}")

# ====== Run ======
if __name__ == "__main__":
    bot.run(TOKEN)

