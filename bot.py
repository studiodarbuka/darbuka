import discord
from discord import app_commands
import os
import asyncio
import datetime
import json

# -----------------------------
# 初期設定
# -----------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# -----------------------------
# 永続ディスク設定（Render有料版）
# -----------------------------
PERSISTENT_DIR = "/data/testbot"  # テストBot用永続ディスク
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "vote_data.json")

file_lock = asyncio.Lock()  # 同時アクセス用ロック

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

        # 他の選択肢から削除
        for k in vote_data[message_id][self.date_str]:
            if user_id in vote_data[message_id][self.date_str][k]:
                vote_data[message_id][self.date_str][k].remove(user_id)

        # 新しい選択肢に追加
        vote_data[message_id][self.date_str][status].append(user_id)
        await save_json(VOTE_FILE, vote_data)

        # Embed更新
        def ids_to_display(ids):
            names = []
            for uid in ids:
                member = interaction.guild.get_member(int(uid))
                if member:
                    names.append(member.display_name)
                else:
                    names.append(f"<@{uid}>")
            return "\n".join(names) if names else "なし"

        embed = interaction.message.embeds[0]
        for idx, k in enumerate(["参加(🟢)", "調整可(🟡)", "不可(🔴)"]):
            users = vote_data[message_id][self.date_str][k]
            embed.set_field_at(idx, name=k, value=ids_to_display(users), inline=False)

        await interaction.response.edit_message(embed=embed, view=self)

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
# /event_now コマンド（手動作成用）
# -----------------------------
@tree.command(name="event_now", description="突発イベントを作成（テスト用）")
@app_commands.describe(
    title="イベント名",
    date="投票日程（カンマ区切り、形式: YYYY-MM-DD）",
    description="詳細（任意）"
)
async def event_now(interaction: discord.Interaction, title: str, date: str, description: str = ""):
    await interaction.response.defer(ephemeral=True)
    dates = []
    for d in date.split(","):
        try:
            parsed = datetime.datetime.strptime(d.strip(), "%Y-%m-%d").strftime("%m/%d(%a)")
            dates.append(parsed)
        except ValueError:
            await interaction.followup.send(f"⚠️ 日付フォーマット不正: {d}", ephemeral=True)
            return

    for d in dates:
        embed = discord.Embed(title=f"【突発イベント】{title} - {d}", description=description or "詳細なし")
        embed.add_field(name="参加(🟢)", value="なし", inline=False)
        embed.add_field(name="調整可(🟡)", value="なし", inline=False)
        embed.add_field(name="不可(🔴)", value="なし", inline=False)
        await interaction.channel.send(embed=embed, view=VoteView(d))

    await interaction.followup.send(f"🚨 イベント「{title}」を作成しました！", ephemeral=True)

# -----------------------------
# バックグラウンドタスク（毎日14:40に自動作成）
# -----------------------------
async def scheduler_task():
    await bot.wait_until_ready()
    TEST_CHANNEL_ID = int(os.getenv("TEST_CHANNEL_ID"))
    channel = bot.get_channel(TEST_CHANNEL_ID)
    if not channel:
        print("⚠️ TEST_CHANNEL_ID のチャンネルが見つかりません")
        return

    while not bot.is_closed():
        now = datetime.datetime.now()
        # 14:40になったら実行
        if now.hour == 14 and now.minute == 40:
            date_str = now.strftime("%m/%d(%a)")
            embed = discord.Embed(title=f"【自動テストイベント】{date_str}", description="テスト用イベント")
            embed.add_field(name="参加(🟢)", value="なし", inline=False)
            embed.add_field(name="調整可(🟡)", value="なし", inline=False)
            embed.add_field(name="不可(🔴)", value="なし", inline=False)
            await channel.send(embed=embed, view=VoteView(date_str))
            #
