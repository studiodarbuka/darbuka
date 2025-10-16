import os
import discord
from discord import app_commands
from discord.ext import commands
import asyncio
import datetime
import pytz
import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ====== 基本設定 ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # メンバー情報取得必須
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ====== 永続保存設定 ======
PERSISTENT_DIR = "/opt/render/project/src/data"
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

# ====== スケジュール生成 ======
def get_schedule_start():
    today = datetime.datetime.now(JST)
    days_until_sunday = (6 - today.weekday()) % 7
    target = today + datetime.timedelta(days=days_until_sunday + 14)
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

        # 既存投票チェック
        user_current_status = None
        for k, v in vote_data[message_id][self.date_str].items():
            if user_name in v:
                user_current_status = k
                break

        # トグル式投票（複数選択不可）
        if user_current_status == status:
            vote_data[message_id][self.date_str][status].remove(user_name)
        else:
            for k in vote_data[message_id][self.date_str]:
                if user_name in vote_data[message_id][self.date_str][k]:
                    vote_data[message_id][self.date_str][k].remove(user_name)
            vote_data[message_id][self.date_str][status].append(user_name)

        save_votes()

        # Embed 更新
        embed = discord.Embed(title=f"【予定候補】{self.date_str}")
        for k, v in vote_data[message_id][self.date_str].items():
            if isinstance(v, list):
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

# ====== Step1: 三週間前スケジュール通知 ======
async def send_step1_schedule():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="wqwq")
    if not channel:
        print("⚠️ チャンネル「wqwq」が見つかりません。")
        return

    week = generate_week_schedule()
    for date in week:
        embed_title = f"📅 三週間後の予定（投票開始） {date}"
        message_id_placeholder = f"tmp-{date}"
        vote_data[message_id_placeholder] = {date: {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}}
        save_votes()

        embed = discord.Embed(title=embed_title)
        for k, v in vote_data[message_id_placeholder][date].items():
            embed.add_field(name=f"{k} ({len(v)}人)", value="\n".join(v) if v else "0人", inline=False)

        view = VoteView(date)
        msg = await channel.send(embed=embed, view=view)
        vote_data[str(msg.id)] = vote_data.pop(message_id_placeholder)
        save_votes()

    print("✅ Step1: 三週間前スケジュール投稿完了。")

# ====== Step2: 二週間前リマインド ======
async def send_step2_remind():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    header = "⏰ **2週間前になりました！投票をお願いします！**\n以下、現状の投票状況です：\n"

    for message_id, dates in vote_data.items():
        for date_str, votes in dates.items():
            lines = [header, f"📅 {date_str}"]
            for status, users in votes.items():
                if isinstance(users, list):
                    lines.append(f"- {status} ({len(users)}人): " + (", ".join(users) if users else "なし"))
            text_msg = "```\n" + "\n".join(lines) + "\n```"
            await channel.send(text_msg)

    print("✅ Step2: 2週間前リマインド送信完了。")

# ====== Step3: 1週間前未投票者通知 + 日付ごと確定通知 ======
async def send_step3_confirm():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name="日程")
    if not channel:
        print("⚠️ チャンネル「日程」が見つかりません。")
        return

    load_votes()
    exclude_users = [bot.user.display_name, "あなたの表示名"]  # Bot と自分を除外

    for message_id, dates in vote_data.items():
        message_id = str(message_id)
        for date_str, votes in dates.items():
            if not votes:
                continue

            # --- 未投票者通知 ---
            voted_users = set()
            for user_list in votes.values():
                if isinstance(user_list, list):
                    voted_users.update(user_list)

            guild = channel.guild
            all_members = {m.display_name: m for m in guild.members}

            unvoted_mentions = []
            for user_name, member_obj in all_members.items():
                if user_name not in voted_users and user_name not in exclude_users:
                    unvoted_mentions.append(member_obj.mention)

            unvoted_text = ", ".join(unvoted_mentions) if unvoted_mentions else "なし"
            await channel.send(f"📅 {date_str}\n未投票者: {unvoted_text}")

            # --- 参加票数3人以上で確定通知 ---
            participants = votes.get("参加(🟢)", [])
            if len(participants) >= 3 and not votes.get("確定通知済み"):
                member_mentions = []
                for member in guild.members:
                    if member.display_name in participants:
                        member_mentions.append(member.mention)

                confirm_msg = (
                    f"こんにちは！今週のレッスン日程が決まったよ！\n\n"
                    f"日時：{date_str}\n"
                    f"場所：朝霧台駅前 ABLE I 2st\n"
                    f"メンバー：{' '.join(member_mentions)}\n\n"
                    f"調整ありがとう、当日は遅れずに来てね！"
                )

                await channel.send(confirm_msg)
                votes["確定通知済み"] = True
                save_votes()
                print(f"✅ 確定通知送信: {date_str}")

    print("✅ Step3: 1週間前未投票者通知＋確定通知完了。")

# ====== /event_now コマンド ======
@tree.command(name="event_now", description="突発イベントを作成します")
@app_commands.describe(
    title="イベントのタイトル",
    date="YYYY-MM-DD形式の日付",
    detail="詳細（任意）"
)
async def event_now(interaction: discord.Interaction, title: str, date: str, detail: str = "詳細なし"):
    try:
        datetime.datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        await interaction.response.send_message("⚠ 日付は YYYY-MM-DD 形式で入力してください。", ephemeral=True)
        return

    embed = discord.Embed(title=f"📢 {title}", color=0x00BFFF)
    embed.add_field(name="📅 日付", value=date, inline=False)
    embed.add_field(name="📝 詳細", value=detail, inline=False)
    embed.set_footer(text="投票してください！ 🟢参加 / 🟡オンライン可 / 🔴不可")

    view = VoteView(date)
    await interaction.response.defer()
    msg = await interaction.channel.send(embed=embed, view=view)

    vote_data[str(msg.id)] = {date: {"参加(🟢)": [], "オンライン可(🟡)": [], "不可(🔴)": []}}
    save_votes()
    await interaction.followup.send("✅ 突発イベントを作成しました！", ephemeral=True)

# ====== on_ready ======
scheduler = AsyncIOScheduler(timezone=JST)

# ====== on_ready ======
@bot.event
async def on_ready():
    load_votes()
    try:
        await tree.sync()
        print("✅ Slash Commands synced!")
    except Exception as e:
        print(f"⚠️ コマンド同期エラー: {e}")

    now = datetime.datetime.now(JST)

    # 本番用に時間を指定（ここでは例として18:42/18:44/18:46）
    three_week_test = now.replace(hour=18, minute=42, second=0, microsecond=0)
    two_week_test = now.replace(hour=18, minute=44, second=0, microsecond=0)
    one_week_test = now.replace(hour=18, minute=46, second=0, microsecond=0)

    scheduler.add_job(send_step1_schedule, DateTrigger(run_date=three_week_test))
    scheduler.add_job(send_step2_remind, DateTrigger(run_date=two_week_test))
    scheduler.add_job(send_step3_confirm, DateTrigger(run_date=one_week_test))
    scheduler.start()

    print(f"✅ Logged in as {bot.user}")
    print("✅ Scheduler started.")


# ====== メイン ======
if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError("❌ DISCORD_BOT_TOKEN が設定されていません。")
    bot.run(token)
