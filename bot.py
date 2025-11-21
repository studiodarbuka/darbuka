# bot.py
import os
import discord
from discord import app_commands
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
import datetime
import pytz
import json
import asyncio

# -----------------------------
# 設定
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("環境変数 DISCORD_BOT_TOKEN を設定してください。")

JST = pytz.timezone("Asia/Tokyo")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

DATA_DIR = "./data"
os.makedirs(DATA_DIR, exist_ok=True)
VOTE_FILE = os.path.join(DATA_DIR, "votes.json")
LOC_FILE = os.path.join(DATA_DIR, "locations.json")
CONFIRMED_FILE = os.path.join(DATA_DIR, "confirmed.json")

# データ
vote_data = {}      # message_id -> {"channel": id, "YYYY-MM-DD (曜)": {statuses...}}
locations = {}      # {"共通": [name,...]}
confirmed = {}      # key -> info

# -----------------------------
# ヘルパー: JSON読み書き
# -----------------------------

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

# -----------------------------
# 日付処理
# 日曜始まりの3週間後の週 (例: 今が 2025-11-21 -> 12月第2週)
# -----------------------------

def get_schedule_start(weeks_ahead=3):
    now = datetime.datetime.now(JST)
    # 今週の日曜日を求める（weekday: Mon=0..Sun=6）
    days_since_sunday = (now.weekday() + 1) % 7
    this_sunday = now - datetime.timedelta(days=days_since_sunday)
    target = this_sunday + datetime.timedelta(weeks=weeks_ahead)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)


def generate_week_schedule(start):
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
    return f"{month}月第{week_number}週"

# -----------------------------
# ユーティリティ
# -----------------------------

def role_by_name(guild, name):
    if not guild: return None
    return discord.utils.get(guild.roles, name=name)


def has_admin_privilege(member: discord.Member):
    if member.guild_permissions.administrator:
        return True
    # 管理者ロール名を持っている場合
    admin_role = role_by_name(member.guild, "管理者")
    if admin_role and admin_role in member.roles:
        return True
    return False

# -----------------------------
# VoteView
# -----------------------------
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

        # トグル
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
        embed = discord.Embed(title=f"📅 予定候補: {self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v.values()) if v else "0人", inline=False)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            pass

        # 自動通知: 参加1名以上で人数確定通知
        participants = vote_data[message_id][self.date_str]["参加(🟢)"]
        if len(participants) >= 1:
            key = f"{message_id}|{self.date_str}"
            if confirmed.get(key) is None:
                confirmed[key] = {"notified": True, "participants": list(participants.values())}
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

# -----------------------------
# ConfirmViewWithImage & Studio selection
# -----------------------------
class ConfirmViewWithImage(discord.ui.View):
    def __init__(self, level, date_str, notice_key=None):
        super().__init__(timeout=None)
        self.level = level
        self.date_str = date_str
        self.notice_key = notice_key

    @discord.ui.button(label="開催する", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 講師権限チェック
        role = role_by_name(interaction.guild, "講師")
        if role and role not in interaction.user.roles:
            await interaction.response.send_message("⚠️ この操作は講師のみ可能です。", ephemeral=True)
            return

        await interaction.response.send_message("🏷 /place に登録している場所から選んでください。", ephemeral=True)

        # ロケーションが無ければ通知
        locs = load_locations().get("共通", [])
        if not locs:
            await interaction.followup.send("⚠️ スタジオが未登録です。/place 登録 <名前> で追加してください。", ephemeral=True)
            return

        view = StudioSelectView(self.date_str, locs, self.notice_key)
        await interaction.followup.send("🏢 スタジオを選択してください。", view=view, ephemeral=True)

    @discord.ui.button(label="開催しない", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 講師権限チェック
        role = role_by_name(interaction.guild, "講師")
        if role and role not in interaction.user.roles:
            await interaction.response.send_message("⚠️ この操作は講師のみ可能です。", ephemeral=True)
            return

        # 不開催処理: 元の投票チャンネルへ通知
        if self.notice_key:
            info = confirmed.setdefault(self.notice_key, {})
            info.update({"final": "不開催", "confirmed_by": interaction.user.display_name, "timestamp": datetime.datetime.now(JST).isoformat()})
            save_confirmed()
            src_channel_id = info.get("source_channel")
            ch = bot.get_channel(src_channel_id) if src_channel_id else None
            if ch:
                await ch.send(f"❌ {self.date_str} は開催不可と講師が判断しました。")
        await interaction.response.send_message("✅ 不開催を送信しました。", ephemeral=True)

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
        # 画像を送るように促す
        await interaction.response.send_message("画像をこのチャンネルにアップロードしてください。無ければ `skip` と入力してください。", ephemeral=True)

        def check(msg):
            return msg.author == interaction.user and msg.channel == interaction.channel

        try:
            msg = await bot.wait_for('message', check=check, timeout=300)
            if msg.content.lower() == "skip":
                image_url = None
            elif msg.attachments:
                image_url = msg.attachments[0].url
            else:
                image_url = None
        except asyncio.TimeoutError:
            image_url = None
            await interaction.followup.send("⏰ 画像送信タイムアウト。スキップ扱いにします。", ephemeral=True)

        # 確定情報保存
        if self.notice_key:
            info = confirmed.setdefault(self.notice_key, {})
            info.update({
                "final": "確定",
                "studio": studio,
                "image_url": image_url,
                "confirmed_by": interaction.user.display_name,
                "timestamp": datetime.datetime.now(JST).isoformat()
            })
            save_confirmed()

            # 元の投票チャンネルへ確定を送信
            src_channel_id = info.get("source_channel")
            ch = bot.get_channel(src_channel_id) if src_channel_id else None
            if ch:
                embed = discord.Embed(title="✅【開催確定】", description=f"{self.date_str} は **{studio}** で開催が確定しました。参加者の皆さん、よろしくお願いします！")
                if image_url:
                    embed.set_image(url=image_url)
                await ch.send(embed=embed)

        try:
            await interaction.followup.send(f"✅ {studio} を選択し、確定処理を完了しました。", ephemeral=True)
        except Exception:
            pass

# -----------------------------
# 確定通知 helper
# -----------------------------
async def send_confirm_notice(guild: discord.Guild, level: str, date_str: str, participants: list, notice_key: str = None, source_channel_id: int = None):
    # 人数確定通知所チャネルを探す（無ければ作成）
    confirm_channel = discord.utils.get(guild.text_channels, name="人数確定通知所")
    if not confirm_channel:
        # 作成する場合はデフォルトカテゴリなしで作る
        confirm_channel = await guild.create_text_channel("人数確定通知所")

    role = role_by_name(guild, "講師")
    mention = role.mention if role else "@講師"
    participants_list = ", ".join(participants) if participants else "なし"
    if notice_key:
        confirmed.setdefault(notice_key, {})
        confirmed[notice_key].update({"source_channel": source_channel_id})
        save_confirmed()

    embed = discord.Embed(title="📢 人数確定通知",
                          description=(f"日程: {date_str}\n級: {level}\n参加者 ({len(participants)}人): {participants_list}\n\n{mention} さん、開催可否を選択してください。"))
    view = ConfirmViewWithImage(level, date_str, notice_key=notice_key)
    await confirm_channel.send(embed=embed, view=view)

# -----------------------------
# /place コマンド
# -----------------------------
@tree.command(name="place", description="スタジオを管理します（登録/削除/一覧）")
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

# -----------------------------
# Scheduler (本番: 毎週日曜 9:00 に Step1)
# - ただし、テスト目的で管理者が即時実行できるコマンドを用意
# -----------------------------
scheduler = AsyncIOScheduler(timezone=JST)

async def schedule_step1():
    await bot.wait_until_ready()
    guild = bot.guilds[0]
    start = get_schedule_start(weeks_ahead=3)
    week_name = get_week_name(start)
    week = generate_week_schedule(start)

    for cat_name in ["初級", "中級"]:
        category = discord.utils.get(guild.categories, name=cat_name)
        ch_name = f"{week_name}-{cat_name}"
        ch = discord.utils.get(guild.text_channels, name=ch_name)
        # 権限設定: 講師, 初級/中級, 管理者 のみ閲覧
        overwrites = {}
        everyone = guild.default_role
        overwrites[everyone] = discord.PermissionOverwrite(view_channel=False)
        role_teacher = role_by_name(guild, "講師")
        role_level = role_by_name(guild, cat_name)
        role_admin = role_by_name(guild, "管理者")
        if role_teacher:
            overwrites[role_teacher] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        if role_level:
            overwrites[role_level] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        if role_admin:
            overwrites[role_admin] = discord.PermissionOverwrite(view_channel=True, send_messages=True)

        if not ch:
            ch = await guild.create_text_channel(ch_name, category=category, overwrites=overwrites)
        else:
            # 既存があれば権限を更新
            try:
                await ch.edit(overwrites=overwrites)
            except Exception:
                pass

        for date in week:
            embed = discord.Embed(title=f"📅 {date}")
            embed.add_field(name="参加(🟢)", value="0人", inline=False)
            embed.add_field(name="オンライン可(🟡)", value="0人", inline=False)
            embed.add_field(name="不可(🔴)", value="0人", inline=False)
            view = VoteView(date)
            msg = await ch.send(embed=embed, view=view)
            vote_data[str(msg.id)] = {"channel": ch.id, date: {"参加(🟢)": {}, "オンライン可(🟡)": {}, "不可(🔴)": {}}}
    save_votes()
    print("✅ Step1 完了: チャンネル作成と投票メッセージ送信")

async def schedule_step2():
    await bot.wait_until_ready()
    # Step1で作成されたメッセージごとに、当該チャンネルのメンバーのみで投票状況表示
    for msg_id, data in list(vote_data.items()):
        ch = bot.get_channel(data.get("channel"))
        if not ch:
            continue
        for date_str, votes in data.items():
            if date_str == "channel":
                continue
            # チャンネル内メンバー
            members = [m for m in ch.members if not m.bot]
            participants = votes["参加(🟢)"]
            online = votes["オンライン可(🟡)"]
            cannot = votes["不可(🔴)"]
            embed = discord.Embed(title=f"{ch.name} の投票状況通知です！")
            embed.add_field(name="日程", value=date_str, inline=False)
            embed.add_field(name=f"参加者 ({len(participants)}人)", value=("\n".join(participants.values()) if participants else "なし"), inline=False)
            embed.add_field(name=f"不可 ({len(cannot)}人)", value="表示なし", inline=False)
            embed.add_field(name=f"オンライン可 ({len(online)}人)", value=("\n".join(online.values()) if online else "なし"), inline=False)
            await ch.send(embed=embed)
    print("✅ Step2 完了: 投票状況通知送信")

async def schedule_step3():
    await bot.wait_until_ready()
    for msg_id, data in list(vote_data.items()):
        ch = bot.get_channel(data.get("channel"))
        if not ch:
            continue
        for date_str, votes in data.items():
            if date_str == "channel":
                continue
            # 未投票者 = チャンネル内メンバーのうち、どのステータスにも入っていない
            voted_ids = set()
            for v in votes.values():
                voted_ids.update(v.keys())
            unvoted = [m for m in ch.members if not m.bot and str(m.id) not in voted_ids]
            # 除外: 講師ロール、管理者ロール
            exclude_roles = {"講師", "管理者"}
            to_mention = []
            for m in unvoted:
                if any(r.name in exclude_roles for r in m.roles):
                    continue
                to_mention.append(m.mention)
            if to_mention:
                await ch.send(f"⏰ リマインド！未投票の方: {', '.join(to_mention)} さん、投票をお願いします！")
    print("✅ Step3 完了: 未投票者へメンション催促")

# Step4 はスケジューラで自動実行しない（投票によって人数確定通知が出るタイミングで人数確定通知所へ送信）

# -----------------------------
# 管理者用テストコマンド (Step1~3 を即時実行可能)
# -----------------------------
@tree.command(name="run_step", description="管理者向け: Step1/2/3 を即時実行（テスト用）")
@app_commands.describe(step="実行するステップ番号 (1/2/3)")
async def run_step(interaction: discord.Interaction, step: int):
    # 管理者チェック
    if not has_admin_privilege(interaction.user):
        await interaction.response.send_message("⚠️ このコマンドは管理者のみ実行できます。", ephemeral=True)
        return
    await interaction.response.send_message(f"実行を受け付けました: Step{step}", ephemeral=True)
    if step == 1:
        await schedule_step1()
    elif step == 2:
        await schedule_step2()
    elif step == 3:
        await schedule_step3()
    else:
        await interaction.followup.send("⚠️ step は 1,2,3 のいずれかを指定してください。", ephemeral=True)

# -----------------------------
# 実行
# -----------------------------
if __name__ == '__main__':
    bot.run(TOKEN)

# ====== on_ready ======
@bot.event
async def on_ready():
    load_votes()
    load_locations()
    load_confirmed()
    try:
        await tree.sync()
        print(f"✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠ コマンド同期エラー: {e}")

    now = datetime.datetime.now(JST)
    three_week_test = now.replace(hour=12, minute=33, second=0, microsecond=0)
    two_week_test   = now.replace(hour=12, minute=34, second=0, microsecond=0)
    one_week_test   = now.replace(hour=12, minute=35, second=0, microsecond=0)

    if three_week_test <= now: three_week_test += datetime.timedelta(days=1)
    if two_week_test   <= now: two_week_test   += datetime.timedelta(days=1)
    if one_week_test   <= now: one_week_test   += datetime.timedelta(days=1)

    if not scheduler.running:
        scheduler.start()

    for jid in ("step1", "step2", "step3"):
        try:
            if scheduler.get_job(jid):
                scheduler.remove_job(jid)
        except Exception:
            pass

    scheduler.add_job(schedule_step1, trigger=DateTrigger(run_date=three_week_test), id="step1")
    scheduler.add_job(schedule_step2, trigger=DateTrigger(run_date=two_week_test), id="step2")
    scheduler.add_job(schedule_step3, trigger=DateTrigger(run_date=one_week_test), id="step3")

    print(f"✅ Logged in as {bot.user}")
    print(f"✅ Scheduler started. Step1~3 scheduled at: {three_week_test}, {two_week_test}, {one_week_test}")

# ====== Run ======
if __name__ == "__main__":
    bot.run(TOKEN)



