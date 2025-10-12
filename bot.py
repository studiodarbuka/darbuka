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
PERSISTENT_DIR = "/data"
os.makedirs(PERSISTENT_DIR, exist_ok=True)
VOTE_FILE = os.path.join(PERSISTENT_DIR, "vote_data.json")

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

# -----------------------------
# VoteView（ボタン）
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
# テスト用チャンネル登録コマンド
# -----------------------------
test_channel = None

@tree.command(name="set_test_channel", description="このチャンネルを自動テスト送信先に設定")
async def set_test_channel(interaction: discord.Interaction):
    global test_channel
    test_channel = interaction.channel
    await interaction.response.send_message("✅ このチャンネルをテスト送信先に設定しました。", ephemeral=True)

# -----------------------------
# 自動スケジュールタスク（毎日13:30）
# -----------------------------
async def auto_schedule_task():
    await bot.wait_until_ready()
    global test_channel
    while not bot.is_closed():
        if test_channel is None:
            print("⚠️ テスト送信先チャンネルが未設定")
            await asyncio.sleep(60)
            continue

        now = datetime.datetime.now()
        target = now.replace(hour=13, minute=30, second=0, microsecond=0)
        if now >= target:
            target += datetime.timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)

        # 7日分自動送信
        today = datetime.date.today()
        for i in range(7):
            d = (today + datetime.timedelta(days=i)).strftime("%m/%d(%a)")
            embed = discord.Embed(title=f"【自動スケジュール】{d}", description="簡易テスト用")
            embed.add_field(name="参加(🟢)", value="なし", inline=False)
            embed.add_field(name="調整可(🟡)", value="なし", inline=False)
            embed.add_field(name="不可(🔴)", value="なし", inline=False)
            await test_channel.send(embed=embed, view=VoteView(d))
        print("✅ 自動スケジュール送信完了")

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
    bot.loop.create_task(auto_schedule_task())
    print("⏰ Auto schedule task started")

# -----------------------------
# 実行
# -----------------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("⚠️ DISCORD_BOT_TOKEN が設定されていません。")

bot.run(TOKEN)
