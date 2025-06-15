import os
import io
import json
import csv
import random
import datetime
import time
from collections import defaultdict

import discord
from discord.ext import commands
from discord import Embed

# ───── 파일 경로 정의 ─────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
TALENT_STORE_FILE = os.path.join(BASE_DIR, "talent_store.json")

# ───── 데이터 통합 관리 ─────
DEFAULT_DATA = {
    "user_points": {},
    "activity_xp": {},
    "admin_xp": {},
    "gamble_points": {},
    "gamble_losses": {},
    "user_levels": {},
    "checkin_log": {},
    "streak_log": {},
    "point_log": {},
    "daily_gamble_log": {},
    "slot_jackpot": 0,
    "slot_attempts": {},
    "beg_log": {},
    "usernames": {},
    "inventory": {}
}

# ───── JSON 읽기/쓰기 ─────
def read_data():
    if not os.path.exists(DATA_FILE):
        return DEFAULT_DATA.copy()
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for key in DEFAULT_DATA:
                data.setdefault(key, DEFAULT_DATA[key])
            return data
    except:
        return DEFAULT_DATA.copy()

def write_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ───── 재능상점 데이터 I/O ─────
def load_talent_store():
    if not os.path.exists(TALENT_STORE_FILE):
        return {}
    try:
        with open(TALENT_STORE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_talent_store(store):
    with open(TALENT_STORE_FILE, 'w', encoding='utf-8') as f:
        json.dump(store, f, indent=2, ensure_ascii=False)

# ───── 레벨 시스템 ─────
def xp_for_next(level):
    return 100 + level * 20

def calculate_level(total_xp):
    level = 1
    while total_xp >= xp_for_next(level):
        total_xp -= xp_for_next(level)
        level += 1
    remaining = xp_for_next(level) - total_xp
    return level, remaining

def get_rank(level):
    if level >= 100: return "Challenger"
    if level >= 99: return "GrandMaster"
    if level >= 89: return "Master"
    if level >= 79: return "Diamond"
    if level >= 69: return "Emerald"
    if level >= 59: return "Platinum"
    if level >= 49: return "Gold"
    if level >= 39: return "Silver"
    if level >= 29: return "Bronze"
    if level >= 19: return "Iron"
    return "Unrank"

# ───── 버튼 설정 ─────
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❗ BOT_TOKEN 환경변수가 설정되지 않았습니다.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ───── 출석 ─────
MILESTONES = {5: 50, 10: 100, 15: 150, 20: 200, 30: 300, 50: 500, 75: 750, 100: 1000}
GIVERS = ["Margo", "지봄이", "노듀오", "리망쿠", "인영킴이", "영규", "슝슝이", "재앙이"]

@bot.command()
async def 출석(ctx):
    data = read_data()
    uid = str(ctx.author.id)
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    data["checkin_log"].setdefault(uid, [])
    data["streak_log"].setdefault(uid, 0)
    data["user_points"].setdefault(uid, 0)
    data["activity_xp"].setdefault(uid, 0)

    if today in data["checkin_log"][uid]:
        await ctx.send(f"❗ 이미 {today}에 출석하셨습니다.")
        return

    if yesterday in data["checkin_log"][uid]:
        data["streak_log"][uid] += 1
    else:
        data["streak_log"][uid] = 1

    base_reward = 50
    bonus = random.choice([40 if random.random() < 0.05 else random.randint(1, 5) if random.random() < 0.3 else 0])
    total = base_reward + bonus

    data["user_points"][uid] += total
    data["activity_xp"][uid] += total
    data["checkin_log"][uid].append(today)

    total_checkins = len(data["checkin_log"][uid])
    milestone_bonus = MILESTONES.get(total_checkins, 0)
    milestone_msg = ""

    if milestone_bonus:
        data["user_points"][uid] += milestone_bonus
        data["activity_xp"][uid] += milestone_bonus
        giver = random.choice(GIVERS)
        meme = random.choice([
            f"{giver}가 포인트를 던지고 사라졌습니다! 🏃‍♂️",
            f"{giver}가 '이 정도면 만족?' {milestone_bonus}포인트 던짐~ 😏"
        ])
        milestone_msg = f"🎯 누적 {total_checkins}일 출석 보상 획득! {meme}"

    write_data(data)

    # 임베드로 출력
    embed = discord.Embed(
        title=f"** {ctx.author.display_name} 님 출석 완료!**",
        description=(
            f"• 📅 출석 보상 : {total}포인트 획득!\n"
            f"• 🏃🏻 누적 출석 {total_checkins}일, 연속 {data['streak_log'][uid]}일"
        ),
        color=discord.Color.green()
    )

    if milestone_bonus:
        embed.add_field(name="🎯 추가 보상", value=milestone_msg, inline=False)

    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command()
async def 출석현황(ctx):
    data = read_data()
    uid = str(ctx.author.id)
    total_days = len(data["checkin_log"].get(uid, []))
    streak_days = data["streak_log"].get(uid, 0)

    next_milestone = next((m for m in sorted(MILESTONES) if total_days < m), None)
    remain_text = (
        f"🔥 다음 출석 보상까지 {next_milestone - total_days}일 남았습니다."
        if next_milestone else "🎉 최고 보상까지 모두 도달했습니다!"
    )

    embed = discord.Embed(
        title=f"**📊 {ctx.author.display_name} 님의 출석 현황**",
        description=(
            f"• 🏃🏻 누적 출석 {total_days}일, 연속 {streak_days}일\n"
            f"• {remain_text}"
        ),
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)

    await ctx.send(embed=embed)

# ───── 포인트 조회 ─────
@bot.command()
async def 포인트(ctx):
    data = read_data()
    uid = str(ctx.author.id)

    total_activity = data['activity_xp'].get(uid, 0)
    total_admin = data['admin_xp'].get(uid, 0)
    total_xp = total_activity + total_admin

    lvl, remain = calculate_level(total_xp)
    cur_xp = total_xp - sum(xp_for_next(i) for i in range(1, lvl))
    prog = int(cur_xp / xp_for_next(lvl) * 10)
    bar = "▰" * prog + "▱" * (10 - prog)

    pts = data['user_points'].get(uid, 0)
    rank = next((i+1 for i, (u, _) in enumerate(sorted(data['user_points'].items(), key=lambda x: x[1], reverse=True)) if u == uid), None)

    embed = Embed(title=f"{ctx.author.display_name}님의 포인트 & 레벨 정보", color=0x55CCFF)
    embed.description = (
        f"• 🏃🏻 레벨 : {get_rank(lvl)} ({lvl})\n"
        f"  📈 진척도 : {bar}\n\n"
        f"• 🔼 다음 레벨까지 : {remain:,} 포인트\n"
        f"• 📊 전체 랭킹 : {rank}위 / {len(data['user_points'])}명 중\n\n"
        f"• 💰 총 보유 포인트 : {pts:,} 포인트\n\n"
        f"• 🎧 획득 포인트 내역:\n"
        f"   └ 활동 포인트 : {total_activity:,}\n"
        f"   └ 관리자 지급 : {total_admin:,}"
    )
    await ctx.send(embed=embed)

# ───── 관리자 수동 지급 ─────
allowed_admin_ids = [518697602774990859, 1335240110358265967]

@bot.command()
async def 지급(ctx, member: discord.Member, 점수: int):
    if ctx.author.id not in allowed_admin_ids:
        await ctx.send("🚫 관리자만 사용 가능합니다")
        return

    data = read_data()
    uid = str(member.id)
    data['user_points'][uid] = data['user_points'].get(uid, 0) + 점수
    data['admin_xp'][uid] = data['admin_xp'].get(uid, 0) + 점수

    write_data(data)
    await ctx.send(f"✅ {member.display_name}님에게 {점수}포인트 지급 완료!👍🏻")

# ───── 구걸 시스템 ─────
@bot.command()
async def 구걸(ctx):
    data = read_data()
    uid = str(ctx.author.id)
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")

    data['beg_log'].setdefault(uid, [])
    if data['beg_log'][uid].count(today) >= 5:
        await ctx.send(f"❗ 하루 5번까지만 구걸할 수 있어요! (이미 {data['beg_log'][uid].count(today)}회 시도)")
        return

    success = random.random() < 0.85
    if success:
        gain = random.randint(10, 30)
        data['user_points'][uid] = data['user_points'].get(uid, 0) + gain
        msg = f"🙏 {ctx.author.display_name}님이 구걸해서 {gain}포인트를 받았습니다!"
    else:
        fail_msgs = [
            "지나가던 인기가 치만 백고 갔습니다... 😢",
            "창대고듬유가 \"포인트 없어!\" 라고 말했습니다... 💨",
            "YESJ어르신이 지갑을 끝내는 창보리만 했습니다... 🤥",
            "길에서 일규박에게 무시달리였습니다. 형식입니다... 🧰",
            "치형님도 '없다'고 했습니다... 🕳️",
            "코끼리가 '내가 다 쓸어갔다'라고 했더라구요… 🐘",
            "유나대장이 슬차가졌다는 소문이… 😏",
        ]
        reason = random.choice(fail_msgs)
        msg = f"{ctx.author.mention} ❌ 구걸 실패!\n{reason}"

    data['beg_log'][uid].append(today)
    write_data(data)
    await ctx.send(msg)

# ───── 도움말 ─────
@bot.command()
async def 도움말(ctx):
    embed = discord.Embed(title="메카살인기 • 솔라리스 봇 도움말", color=0xFFA500)
    
    embed.add_field(
        name="💡 **포인트 획득**", 
        value=(
            "└ 음성채널 접속 시 자동 적립\n"
            "    └ 🎤 마이크 ON: 1분당 2포인트\n"
            "    └ 🎙️ 마이크 OFF: 1분당 1포인트\n"
            "└ ⚔️ 내전 참여 시 추가 포인트 획득 가능"
        ), 
        inline=False
    )
    
    embed.add_field(
        name="📅 **!출석 : 하루 1회 출석 체크 및 보상 지급**", 
        value="└ `!출석현황` 으로 출석 진행 상황 확인 가능", 
        inline=False
    )
    embed.add_field(name="💰 **!포인트 : 내 포인트, XP, 레벨 확인**", value="", inline=False)
    embed.add_field(name="🏆 **!랭킹 : 상위 10명 순위 확인**", value="", inline=False)
    embed.add_field(name="📊 **!평균 : 평균 인원 수, 총합, 1인 평균 확인**", value="", inline=False)
    embed.add_field(name="🙏 **!구걸 : 하루 제한 횟수 내 추가 포인트 시도**", value="", inline=False)
    embed.add_field(name="🎲 **!도박 금액 : 도박으로 포인트 배수 도전**", value="", inline=False)
    embed.add_field(name="🎰 **!슬롯 : 슬롯머신 참가 및 잭팟 도전**", value="", inline=False)
    embed.add_field(name="📤 **!보내기 @유저 금액 : 다른 유저에게 포인트 전송**", value="", inline=False)
    embed.add_field(name="🛠️ **!지급 @유저 금액 : (관리자) 유저에게 포인트 지급**", value="", inline=False)
    embed.add_field(
        name="🛒 **!재능상점 등록/관리/구경/구매**", 
        value="└ 자세한 사용법은 `!재능상점 도움말` 을 참고해주세요.", 
        inline=False
    )
    
    embed.set_footer(text="메카살인기 • 솔라리스")
    embed.set_thumbnail(url=ctx.me.display_avatar.url)
    await ctx.send(embed=embed)


# ───── 도박 시스템 (최신 확률 적용) ─────
@bot.command()
async def 도박(ctx, 배팅: int):
    data = read_data()
    uid = str(ctx.author.id)

    if 배팅 <= 0:
        await ctx.send("❌ 배팅 금액은 1 이상이어야 합니다.")
        return

    current_points = data['user_points'].get(uid, 0)
    if current_points < 배팅:
        await ctx.send("❌ 보유 포인트가 부족합니다.")
        return

    data['user_points'][uid] -= 배팅
    chance = random.uniform(0, 100)  # 실수 기반 분포
    gain = 0

    if chance < 58.5:
        result_msg = f"💀 실패! {배팅:,}점 잃었습니다."
        data['gamble_losses'][uid] = data['gamble_losses'].get(uid, 0) + 배팅
    elif chance < 94:
        gain = 배팅 * 2
        result_msg = f"✨ 2배 당첨! {gain:,}점 획득!"
    elif chance < 99:
        gain = 배팅 * 3
        result_msg = f"🎉 3배 당첨! {gain:,}점 획득!"
    else:
        gain = 배팅 * 10
        result_msg = f"🌟 10배 전설 당첨! {gain:,}점 획득!!"

    data['user_points'][uid] += gain
    if gain > 0:
        data['gamble_points'][uid] = data['gamble_points'].get(uid, 0) + gain

    write_data(data)

    await ctx.send(f"{ctx.author.mention}\n{result_msg}\n💰 현재 보유 포인트: {data['user_points'][uid]:,}점")

# ───── 슬롯머신 시스템 ─────
@bot.command()
async def 슬롯(ctx):
    data = read_data()
    uid = str(ctx.author.id)
    bet = 10

    if data['user_points'].get(uid, 0) < bet:
        await ctx.send("❌ 포인트 부족 (10점 필요)")
        return

    # 베팅 차감 및 잭팟 누적
    data['user_points'][uid] -= bet
    data['slot_jackpot'] += bet
    data['slot_attempts'][uid] = data['slot_attempts'].get(uid, 0) + 1

    emojis = ["☀️", "🌙", "⭐", "🍀", "💣"]
    chance = random.random()

    if chance < 0.005:  # 솔라잭팟 0.5%
        result = ["☀️"] * 5
    elif chance < 0.015:  # 다른 잭팟 1%
        sym = random.choice(emojis[1:])
        result = [sym] * 5
    else:
        while True:
            result = [random.choice(emojis) for _ in range(5)]
            if len(set(result)) > 1:
                break

    common = max(set(result), key=result.count)
    cnt = result.count(common)
    lines = [f"🎰 결과 : {' '.join(result)}"]

    if cnt == 5:
        reward = int(data['slot_jackpot'] * 0.8)
        bonus_msg = ""
        if common == "☀️":
            reward += 500
            bonus_msg = "• ☀️ **솔라잭팟!** 500포인트 추가 보너스!"

        data['user_points'][uid] += reward
        pool = data['slot_jackpot'] - int(data['slot_jackpot'] * 0.8)

        top2 = sorted(data['slot_attempts'].items(), key=lambda x: x[1], reverse=True)
        recip = [u for u, _ in top2 if u != uid][:2]
        share = pool // len(recip) if recip else 0
        dist = [f"<@{r}> (+{share:,}점)" for r in recip]

        lines.append(f"• 🌟 {common} 5개 잭팟! 획득: {reward:,}점")
        if bonus_msg:
            lines.append(bonus_msg)
        if dist:
            lines.append(f"• 🎁 분배: {' / '.join(dist)}")

        # 잭팟 초기화 (최소 1000점 + 시도횟수만큼 가산)
        data['slot_jackpot'] = 1000 + sum(data['slot_attempts'].values()) * bet
        data['slot_attempts'] = {}
    else:
        lines.append("• 💀 꽝! 잭팟 누적 중...")
        lines.append(f"• 💰 남은 포인트: {data['user_points'][uid]:,}점")
        lines.append(f"• 💸 잭팟: {data['slot_jackpot']:,}점")

    write_data(data)
    embed = Embed(title="**[슬롯머신 결과]**", description="\n".join(lines), color=0xf1c40f)
    await ctx.send(embed=embed)

# ───── 보내기 시스템 ─────
@bot.command()
async def 보내기(ctx, member: discord.Member, 금액: int):
    data = read_data()
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)

    if 금액 <= 0:
        await ctx.send("❌ 1 이상의 금액을 입력하세요.")
        return

    if sender_id == receiver_id:
        await ctx.send("❗ 자신에게는 보낼 수 없습니다.")
        return

    if data['user_points'].get(sender_id, 0) < 금액:
        await ctx.send("😢 포인트가 부족합니다.")
        return

    data['user_points'][sender_id] -= 금액
    data['user_points'][receiver_id] = data['user_points'].get(receiver_id, 0) + 금액

    write_data(data)
    await ctx.send(f"📤 {ctx.author.display_name}님이 {member.display_name}님에게 {금액:,}포인트를 보냈습니다!")

# ───── 재능상점 파일 I/O ─────
TALENT_STORE_FILE = os.path.join(BASE_DIR, "talent_store.json")

def load_talent_store():
    if not os.path.exists(TALENT_STORE_FILE):
        return {}
    try:
        with open(TALENT_STORE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_talent_store(store):
    with open(TALENT_STORE_FILE, 'w', encoding='utf-8') as f:
        json.dump(store, f, indent=2, ensure_ascii=False)


# ───── 재능상점 판매 등록/관리 ─────
@bot.command()
async def 재능상점판매(ctx, action=None, *, args=None):
    user_id = str(ctx.author.id)
    store = load_talent_store()

    if user_id not in store:
        store[user_id] = {"items": []}

    if action == "상품등록":
        if not args:
            return await ctx.send("❗ 등록 형식: !재능상점판매 상품등록 이름 가격")

        parts = args.split()
        if len(parts) < 2:
            return await ctx.send("❗ 등록 형식: !재능상점판매 상품등록 이름 가격")

        name, price = parts[0], int(parts[1])
        store[user_id]["items"].append({"name": name, "price": price})
        save_talent_store(store)
        await ctx.send(f"✅ 상품 '{name}'이(가) 등록되었습니다. 가격: {price}코인")

    elif action == "관리":
        if args and args.endswith(" 삭제"):
            nm = args[:-3].strip()
            before = len(store[user_id]["items"])
            store[user_id]["items"] = [it for it in store[user_id]["items"] if it["name"] != nm]
            save_talent_store(store)

            if len(store[user_id]["items"]) < before:
                return await ctx.send(f"🗑️ 상품 '{nm}'이(가) 삭제되었습니다.")
            else:
                return await ctx.send(f"❌ '{nm}' 상품을 찾을 수 없습니다.")

        items = store[user_id]["items"]
        if not items:
            return await ctx.send("📦 등록된 상품이 없습니다.")

        lines = [f"• {it['name']} — {it['price']}코인" for it in items]
        await ctx.send("**내 상점 상품 목록**\n" + "\n".join(lines))

    else:
        await ctx.send("사용법: !재능상점판매 상품등록/관리 <args>")

# ───── 재능상점 구매 ─────
@bot.command()
async def 재능상점(ctx, action=None, seller: discord.Member = None, *, args=None):
    user_id = str(ctx.author.id)
    store = load_talent_store()
    data = read_data()

    # ───── 등록 ─────
    if action == "등록":
        if user_id not in store:
            store[user_id] = {"items": []}

        if not args:
            return await ctx.send("❗ 등록 형식: !재능상점 등록 상품이름 가격")

        parts = args.split()
        if len(parts) < 2:
            return await ctx.send("❗ 등록 형식: !재능상점 등록 상품이름 가격")

        name, price = parts[0], int(parts[1])
        store[user_id]["items"].append({"name": name, "price": price})
        save_talent_store(store)
        await ctx.send(f"✅ 상품 '{name}'이(가) 등록되었습니다. 가격: {price}코인")

    # ───── 관리 ─────
    elif action == "관리":
        if user_id not in store or not store[user_id]["items"]:
            return await ctx.send("📦 등록된 상품이 없습니다.")

        if args and args.endswith(" 삭제"):
            nm = args[:-3].strip()
            before = len(store[user_id]["items"])
            store[user_id]["items"] = [it for it in store[user_id]["items"] if it["name"] != nm]
            save_talent_store(store)
            
            if len(store[user_id]["items"]) < before:
                return await ctx.send(f"🗑️ 상품 '{nm}'이(가) 삭제되었습니다.")
            else:
                return await ctx.send(f"❌ '{nm}' 상품을 찾을 수 없습니다.")

        lines = [f"• {it['name']} — {it['price']}코인" for it in store[user_id]["items"]]
        await ctx.send("**내 상점 상품 목록**\n" + "\n".join(lines))

    # ───── 구경 (임베드 출력) ─────
    elif action == "구경":
        if not store:
            return await ctx.send("📭 활성화된 재능 상점이 없습니다.")

        embed = discord.Embed(title="🛍️ 재능 상점 판매 목록", color=discord.Color.gold())
        header = f"{'판매자':<12} | {'상품명':<15} | {'가격':<6} | {'상품수':<4}"
        embed.add_field(name="목록", value=f"```{header}\n{'-'*45}```", inline=False)

        lines = []
        for sid, info in store.items():
            member = ctx.guild.get_member(int(sid))
            items = info['items']
            item_count = len(items)

            if not items:
                lines.append(f"{member.display_name:<12} | {'없음':<15} | {'-':<6} | {0:<4}")
                continue

            for item in items:
                line = f"{member.display_name:<12} | {item['name']:<15} | {item['price']}코인 | {item_count:<4}"
                lines.append(line)

        chunk = "```" + "\n".join(lines) + "```"
        embed.add_field(name="상품 목록", value=chunk, inline=False)
        await ctx.send(embed=embed)

    # ───── 구매 ─────
    elif action == "구매" and seller and args:
        sid = str(seller.id)
        item_name = args.strip()

        if sid not in store:
            return await ctx.send("❌ 판매자를 찾을 수 없습니다.")

        match = next((it for it in store[sid]["items"] if it["name"] == item_name), None)
        if not match:
            return await ctx.send("❌ 해당 상품을 찾을 수 없습니다.")

        price = match["price"]
        if data['user_points'].get(user_id, 0) < price:
            return await ctx.send("😢 포인트가 부족합니다.")

        # 포인트 이동
        data['user_points'][user_id] -= price
        data['user_points'][sid] = data['user_points'].get(sid, 0) + price
        write_data(data)

        await ctx.send(f"🎉 {seller.display_name}님의 상품 '{item_name}'을(를) {price}코인에 구매했습니다!")

        # 판매자에게 DM 발송
        try:
            buyer_name = ctx.author.display_name
            dm_msg = (
                f"📢 {buyer_name}님이 당신의 상품 **'{item_name}'**을(를) {price}코인에 구매했습니다!\n"
                f"서버에서 확인해 주세요: {ctx.guild.name}"
            )
            await seller.send(dm_msg)
        except discord.Forbidden:
            await ctx.send(f"⚠️ {seller.mention}님께 DM을 보낼 수 없습니다.")

    else:
        await ctx.send("사용법: !재능상점 등록/관리/구경/구매")

# ───── 랭킹 시스템 ─────
@bot.command()
async def 랭킹(ctx):
    data = read_data()
    if not data['user_points']:
        await ctx.send("📉 아직 데이터가 없습니다.")
        return

    sorted_users = sorted(data['user_points'].items(), key=lambda x: x[1], reverse=True)
    top10 = sorted_users[:10]
    desc = "\n".join(f"**{i+1}.** <@{uid}> — {pt:,}포인트" for i, (uid, pt) in enumerate(top10))

    embed = Embed(title="**🌞 TOP 10 랭킹**", description=desc, color=0xFFD700)
    await ctx.send(embed=embed)

@bot.command()
async def 평균(ctx):
    data = read_data()
    if not data['user_points']:
        await ctx.send("📉 아직 데이터가 없습니다.")
        return

    total = sum(data['user_points'].values())
    cnt = len(data['user_points'])
    avg = total // cnt
    desc = (
        f"• **인원 수**: {cnt}명\n"
        f"• **총합**: {total:,}점\n"
        f"• **1인 평균**: {avg:,}점"
    )
    embed = Embed(title="**📈 전체 평균 포인트**", description=desc, color=0x00AAFF)
    await ctx.send(embed=embed)

# ───── 봇 실행 ─────
print("🤖 디스코드 봇 전체 통합 리팩토링 버전 실행 준비 완료!")
bot.run(TOKEN)
