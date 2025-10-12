import discord
from discord import app_commands
import datetime
import os
import asyncio
import json

# -----------------------------
# 初期設定
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# -----------------------------
# 永続ディスク設定（Render有料版向け）
# -----------------------------
PERSISTENT_DIR = "/data/darbuka_bot"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "vote_data.json")
REMINDER_FILE = os.path.join(PERSISTENT_DIR, "reminders.json")

file_lock = asyncio.Lock()

# -----------------------------
# データ永続化関数
# -----------------------------
def _atomic_write(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

async def save_json(file, data):
    async with file_lock:
        await asyncio.to_thread(_atomic_write, file, data)

async def load_json(file, default):
    if not os.path.exists(file):
        return default
    async with file_lock:
        return await asyncio.to_thread(lambda: json.load(open(file, "r", encoding="utf-8")))

# -----------------------------
# 起動時のデータ読み込み
# -----------------------------
vote_data = asyncio.run(load_json(VOTE_FILE, {}))
scheduled_weeks = asyncio.run(load_json(REMINDER_FILE, {"scheduled": []}))["scheduled"]

# -----------------------------
# VoteView
# -----------------------------
class VoteView(discord.ui.View):
    def __init__(self, date_str):
        super().__init__(timeout=None)
        self.date_str = date_str

    async def register_vote(self, interaction: discord.Interaction, status: str):
        message_id = str(interaction.message.id)
        user_id = str(interaction.user.id)

        if message_id not in vote_data:
            vote_data[message_id] = {}
        if self.date_str not in vote_data[message_id]:
            vote_data[message_id][self.date_str] = {"参加(🟢)": [], "調整可(🟡)": [], "不可(🔴)": []}

        for k in vote_data[message_id][self.date_str]:
            if user_id in vote_data[message_id][self.date_str][k]:
                vote_data[message_id][self.date_str][k].remove(user_id)

        vote_data[message_id][self.date_str][status].append(user_id)
        await save_json(VOTE_FILE, vote_data)

        def ids_to_display(ids):
            names = []
            for uid in ids:
                member = interaction.guild.get_member(int(uid))
                if member:
                    names.append(member.display_name)
                else:
                    names.append(f"<@{uid}>")
            return ", ".join(names) if names else "-"

        embed = interaction.message.embeds[0]
        for idx, k in enumerate(["参加(🟢)", "調整可(🟡)", "不可(🔴)"]):
            users = vote_data[message_id][self.date_str][k]
            embed.set_field_at(idx, name=k, value=ids_to_display(users), inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

        if len(vote_data[message_id][self.date_str]["参加(🟢)"]) >= 3:
            await interaction.channel.send(f"✅ {self.date_str} は3人以上が参加予定！日程確定です！")

    @discord.ui.button(label="参加(🟢)", style=discord.ButtonStyle.green)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "参加(🟢)")

    @discord.ui.button(label="調整可(🟡)", style=discord.ButtonStyle.blurple)
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "調整可(🟡)")

    @discord.ui.button(label="不可(🔴)", style=discord.ButtonStyle.red)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.register_vote(interaction, "不可(🔴)")

# -----------------------------
# /schedule コマンド
# -----------------------------
@tree.command(name="schedule", description="日程調整を開始します")
async def schedule(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    today = datetime.date.today()
    target = today + datetime.timedelta(weeks=3)
    days_to_sunday = (6 - target.weekday()) % 7
    start_date = target + datetime.timedelta(days=days_to_sunday)

    scheduled_weeks.append({
        "channel_name": "日程",
        "start_date": start_date.strftime("%Y-%m-%d"),
        "reminded_2w": False,
        "reminded_1w": False
    })
    await save_json(REMINDER_FILE, {"scheduled": scheduled_weeks})

    dates = [(start_date + datetime.timedelta(days=i)).strftime("%m/%d(%a)") for i in range(7)]
    for d in dates:
        embed = discord.Embed(title=f"【日程候補】{d}", description="以下のボタンで投票してください")
        embed.add_field(name="参加(🟢)", value="-", inline=False)
        embed.add_field(name="調整可(🟡)", value="-", inline=False)
        embed.add_field(name="不可(🔴)", value="-", inline=False)
        await interaction.channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(f"📅 {start_date.strftime('%m/%d(%a)')} からの1週間の日程候補を作成しました！", ephemeral=True)

# -----------------------------
# バックグラウンドタスク（自動リマインド）
# -----------------------------
async def scheduler_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        today = datetime.date.today()
        for s in scheduled_weeks:
            start_date = datetime.datetime.strptime(s["start_date"], "%Y-%m-%d").date()
            channel = None
            for ch in bot.get_all_channels():
                if ch.name == s.get("channel_name"):
                    channel = ch
                    break

            if not channel:
                continue

            # 2週間前リマインド
            if not s.get("reminded_2w") and today == start_date - datetime.timedelta(weeks=2):
                text = "📢 2週間前リマインドです！投票がまだの方はお願いします！\n\n"
                text += "```固定幅表形式\n"
                text += f"{'日程':<10}{'参加':<20}{'調整':<20}{'不可':<20}\n"

                # 投票状況をまとめる
                for msg_id, days in vote_data.items():
                    for date, status in days.items():
                        text += f"{date:<10}"
                        for col in ["参加(🟢)", "調整可(🟡)", "不可(🔴)"]:
                            users = []
                            for uid in status.get(col, []):
                                users.append(f"<@{uid}>")
                            text += f"{', '.join(users) or '-':<20}"
                        text += "\n"
                text += "```"
                await channel.send(text)
                s["reminded_2w"] = True

            # 1週間前リマインド（簡易通知）
            if not s.get("reminded_1w") and today == start_date - datetime.timedelta(weeks=1):
                await channel.send("📅 1週間前確認です！まだ未投票の方はお願いします！")
                s["reminded_1w"] = True

        await save_json(REMINDER_FILE, {"scheduled": scheduled_weeks})
        await asyncio.sleep(60 * 60)  # 1時間ごとにチェック

# -----------------------------
# Bot起動
# -----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")
    try:
        await tree.sync()
        print("✅ Slash commands synced!")
    except Exception as e:
        print(f"❌ Sync error: {e}")
    bot.loop.create_task(scheduler_task())
    print("⏰ Scheduler task started")

# -----------------------------
# 実行
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)
