import os
import io
import json
import csv
import random
import datetime
import time
import asyncio
import re
from collections import defaultdict

import discord
from discord.ext import commands
from discord import Embed

# ───── 파일 경로 정의 ─────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
TALENT_STORE_FILE = os.path.join(BASE_DIR, "talent_store.json")

DEFAULT_DATA = {"user_points": {}}

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

# ───── 파서 완전 안정화 ─────
def extract_name_and_price(args):
    match = re.search(r"\((.*?)\)", args)
    if not match:
        return None, None
    name = match.group(1).strip()
    after_bracket = args[match.end():].strip()
    price_match = re.search(r"(\d+)", after_bracket)
    if not price_match:
        return name, None
    price = int(price_match.group(1))
    return name, price

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
    total_gamble = data['gamble_points'].get(uid, 0)
    total_xp = total_activity + total_admin

    lvl, remain = calculate_level(total_xp)
    cur_xp = total_xp - sum(xp_for_next(i) for i in range(1, lvl))
    prog = int(cur_xp / xp_for_next(lvl) * 10)
    
    bar = "🟩" * prog + "⬛" * (10 - prog)

    pts = data['user_points'].get(uid, 0)
    rank = next((i+1 for i, (u, _) in enumerate(
        sorted(data['user_points'].items(), key=lambda x: x[1], reverse=True)) if u == uid), None)

    embed = Embed(title=f"{ctx.author.display_name}님의 포인트 & 레벨 정보", color=0x55CCFF)
    embed.description = (
        f"• 📈 진척도 : {bar}\n\n"
        f"• 🏃🏻 레벨 : {get_rank(lvl)} ({lvl})\n"
        f"• 🔼 다음 레벨까지 : {remain:,} 포인트\n"
        f"• 📊 전체 랭킹 : {rank}위 / {len(data['user_points'])}명 중\n\n"
        f"• 💰 총 보유 포인트 : {pts:,} 포인트\n"
        f"   └ 활동 포인트 : {total_activity:,}\n"
        f"   └ 관리자 지급 : {total_admin:,}\n"
        f"   └ 도박 포인트 : {total_gamble:,}"
    )

    embed.set_thumbnail(url=ctx.author.display_avatar.url)

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
            "지나가던 인기가 침만 뱉고 갔습니다... 😢",
            "창대곤듀가 \"포인트 없어!\" 라고 말했습니다... 💨",
            "YESJ어르신이 지갑을 끝내는 척만 했습니다... 🤥",
            "길에서 일규박에게 무시당했습니다. 현실입니다... 🧰",
            "침형님도 '포인트 없다'고 했습니다... 😇",
            "코끼리가 '내가 다 쓸어갔다'라고 했습니다… 🐘",
            "유나대장이 슬쩍 가져갔다는 소문이… 😏",
        ]
        reason = random.choice(fail_msgs)
        msg = f"{ctx.author.mention} ❌ 구걸 실패!\n{reason}"

    data['beg_log'][uid].append(today)
    write_data(data)
    await ctx.send(msg)

# ───── 도움말 ─────
@bot.command()
async def 도움말(ctx):
    embed = discord.Embed(title="**메카살인기 • 솔라리스 봇 도움말**", color=0xFFA500)
    
    embed.add_field(
        name="💡 포인트 획득", 
        value=(
            "• 음성 채널 접속 시 자동 적립\n"
            "└ 마이크 ON : 1분당 2포인트\n"
            "└ 마이크 OFF : 1분당 1포인트\n"
            "• ⚔️ 내전 참여 시 추가 포인트 획득 가능"
        ),
        inline=False
    )
    
    embed.add_field(name="📅 `!출석` : 하루 1회 출석 체크 및 보상 지급", 
                    value="└ `!출석현황` 으로 출석 진행 상황 확인 가능", inline=False)
    embed.add_field(name="💰 `!포인트` : 내 포인트, XP, 레벨 확인", value="", inline=False)
    embed.add_field(name="🏆 `!랭킹` : 상위 10명 순위 확인", value="", inline=False)
    embed.add_field(name="📊 `!평균` : 평균 인원 수, 총합, 1인 평균 확인", value="", inline=False)
    embed.add_field(name="🙏 `!구걸` : 하루 제한 횟수 내 추가 포인트 시도", value="", inline=False)
    embed.add_field(name="🎲 `!도박 금액` : 도박으로 포인트 배수 도전", value="", inline=False)
    embed.add_field(name="🎰 `!슬롯` : 슬롯머신 참가 및 잭팟 도전", value="", inline=False)
    embed.add_field(name="📤 `!보내기 @유저 금액` : 다른 유저에게 포인트 전송", value="", inline=False)
    embed.add_field(name="🛠️ `!지급 @유저 금액` : (관리자) 유저에게 포인트 지급", value="", inline=False)
    embed.add_field(
        name="🛒 `!재능상점 등록/관리/구경/구매`", 
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


# ───── 슬롯머신 시스템 애니메이션 풀버전 ─────

BASE_JACKPOT = 1000
BET_AMOUNT = 10
JACKPOT_REWARD_RATIO = 0.8
SOLAR_JACKPOT_BONUS = 500
SOLAR_JACKPOT_CHANCE = 0.005
OTHER_JACKPOT_CHANCE = 0.015

EMOJIS = ["☀️", "🌙", "⭐", "🍀", "💣"]

@bot.command()
async def 슬롯(ctx):
    data = read_data()
    uid = str(ctx.author.id)

    # 유저 포인트 확인
    if data['user_points'].get(uid, 0) < BET_AMOUNT:
        await ctx.send("❌ 포인트 부족 (10포인트 필요)")
        return

    # 누적 베팅 초기화 (최초 1회)
    if "slot_bets" not in data:
        data['slot_bets'] = 0

    # 베팅 반영
    data['user_points'][uid] -= BET_AMOUNT
    data['slot_bets'] += BET_AMOUNT

    # 잭팟 현재금 계산
    current_jackpot = BASE_JACKPOT + data['slot_bets']

    # 결과 미리 결정
    chance = random.random()
    if chance < SOLAR_JACKPOT_CHANCE:
        final_result = ["☀️"] * 5
    elif chance < OTHER_JACKPOT_CHANCE:
        sym = random.choice(EMOJIS[1:])
        final_result = [sym] * 5
    else:
        while True:
            final_result = [random.choice(EMOJIS) for _ in range(5)]
            if len(set(final_result)) > 1:
                break

    # 🎰 애니메이션 (4회 초고속 회전)
    rolling_msg = await ctx.send("🎰 슬롯머신 작동중...")

    for _ in range(4):
        roll = [random.choice(EMOJIS) for _ in range(5)]
        display = f"🎰 | {' '.join(roll)}"
        await rolling_msg.edit(content=display)
        await asyncio.sleep(0.1)

    await asyncio.sleep(0.2)
    await rolling_msg.edit(content=f"🎯 최종 결과 | {' '.join(final_result)}")
    await asyncio.sleep(0.4)

    # 결과 계산
    common = max(set(final_result), key=final_result.count)
    cnt = final_result.count(common)

    lines = []

    if cnt == 5:
        reward = int(current_jackpot * JACKPOT_REWARD_RATIO)
        bonus_msg = ""

        if common == "☀️":
            reward += SOLAR_JACKPOT_BONUS
            bonus_msg = "☀️ **솔라잭팟! 추가 보너스 500포인트!**"

        data['user_points'][uid] += reward

        lines.append(f"🎉 **{common} 5개 잭팟 당첨! {reward:,}포인트 획득!**")
        if bonus_msg:
            lines.append(bonus_msg)

        # 잭팟 완전 초기화
        data['slot_bets'] = 0

    else:
        lines.append("💀 꽝! 누적 상금은 계속 쌓입니다...")
        lines.append(f"💸 누적 잭팟 : {BASE_JACKPOT} + {data['slot_bets']:,} = {current_jackpot:,}포인트")
        lines.append(f"💰 남은 내 포인트 : {data['user_points'][uid]:,}포인트")

    write_data(data)

    embed = discord.Embed(
        title=f"🎰 [{ctx.author.display_name}님의 슬롯 결과]",
        description="\n".join(lines),
        color=0xf1c40f
    )
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
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

# ───── 재능상점 통합 ─────
# 재능상점 통합 명령어
@bot.command()
async def 재능상점(ctx, action=None, seller=None, *, args=None):
    user_id = str(ctx.author.id)
    store = load_talent_store()

    # 상품 등록
    if action == "등록":
        if user_id not in store:
            store[user_id] = {"items": []}
        if not args:
            return await ctx.send("❗ 등록 형식: !재능상점 등록 (상품명) 가격")

        name, price = extract_name_and_price(args)
        if not name or price is None:
            return await ctx.send("❗ 등록 형식: !재능상점 등록 (상품명) 가격")

        store[user_id]["items"].append({"name": name, "price": price})
        save_talent_store(store)
        await ctx.send(f"✅ 상품 '{name}' 이(가) 등록되었습니다. 가격: {price}포인트")

    # 상품 관리
    elif action == "관리":
        if user_id not in store or not store[user_id]["items"]:
            return await ctx.send("📦 등록된 상품이 없습니다.")

        if args and args.endswith(" 삭제"):
            name_match = re.search(r"\((.*?)\)", args)
            if not name_match:
                return await ctx.send("❗ 삭제 형식: !재능상점 관리 (상품명) 삭제")

            name_to_delete = name_match.group(1).strip()
            before = len(store[user_id]["items"])
            store[user_id]["items"] = [it for it in store[user_id]["items"] if it["name"] != name_to_delete]
            save_talent_store(store)

            if len(store[user_id]["items"]) < before:
                return await ctx.send(f"🗑️ 상품 '{name_to_delete}' 이(가) 삭제되었습니다.")
            else:
                return await ctx.send(f"❌ '{name_to_delete}' 상품을 찾을 수 없습니다.")

        lines = [f"• {it['name']} — {it['price']}포인트" for it in store[user_id]["items"]]
        await ctx.send("**내 상점 상품 목록**\n" + "\n".join(lines))

    # 상점 구경
    elif action == "구경":
        if not store:
            return await ctx.send("📭 활성화된 재능 상점이 없습니다.")

        embed = discord.Embed(title="🛍️ 재능상점 전체 목록", color=discord.Color.gold())
        embed.add_field(name="판매자", value="\n".join([ctx.guild.get_member(int(sid)).display_name for sid in store]), inline=True)
        embed.add_field(name="상품명", value="\n".join([" / ".join([it["name"] for it in store[sid]["items"]]) for sid in store]), inline=True)
        embed.add_field(name="가격", value="\n".join([" / ".join([str(it["price"]) for it in store[sid]["items"]]) for sid in store]), inline=True)
        await ctx.send(embed=embed)

    # 상품 구매
    elif action == "구매" and seller and args:
        mention_match = re.search(r'<@!?(\\d+)>', seller)
        if not mention_match:
            return await ctx.send("❗ 구매 형식: !재능상점 구매 @판매자 (상품명)")

        sid = mention_match.group(1)
        member = ctx.guild.get_member(int(sid))
        if not member:
            return await ctx.send("❌ 판매자를 찾을 수 없습니다.")

        if sid not in store:
            return await ctx.send("❌ 판매자의 상점이 없습니다.")

        name_match = re.search(r"\((.*?)\)", args)
        if not name_match:
            return await ctx.send("❗ 구매 형식: !재능상점 구매 @판매자 (상품명)")

        item_name = name_match.group(1).strip()
        match_item = next((it for it in store[sid]["items"] if it["name"] == item_name), None)
        if not match_item:
            return await ctx.send("❌ 해당 상품을 찾을 수 없습니다.")

        await ctx.send(f"🎉 {member.display_name}님의 상품 '{item_name}' 을(를) 구매 요청 완료! (포인트 시스템 연동은 생략)")

    # 도움말 호출
    elif action == "도움말":
        await 재능상점도움말(ctx)

    else:
        usage = (
            "**사용법:**\n"
            "`!재능상점 등록 (상품명) 가격`\n"
            "`!재능상점 관리 [(상품명) 삭제]`\n"
            "`!재능상점 구경`\n"
            "`!재능상점 구매 @판매자 (상품명)`\n"
            "`!재능상점 도움말`"
        )
        await ctx.send(usage)

# 임베드 도움말
async def 재능상점도움말(ctx):
    embed = discord.Embed(
        title="🌞 솔라 재능상점 도움말",
        description="재능상점은 솔라리스 클랜원들이 보유한 다양한 재능을 포인트로 사고 파는 거래 콘텐츠입니다.",
        color=0x00ffcc
    )
    embed.set_thumbnail(url=ctx.bot.user.avatar.url)
    embed.add_field(
        name="🛒 판매하기",
        value="`!재능상점 등록 (상품명) 가격`\n`!재능상점 관리`\n`!재능상점 관리 (상품명) 삭제`",
        inline=False
    )
    embed.add_field(
        name="🎯 구매하기",
        value="`!재능상점 구경`\n`!재능상점 구매 @판매자 (상품명)`",
        inline=False
    )
    embed.add_field(
        name="⚠️ 참고사항",
        value="상품명은 반드시 괄호 ( ) 안에 작성\n띄어쓰기 자유롭게 가능\n구매 시 판매자 @멘션 필수\n포인트 부족 시 구매 불가",
        inline=False
    )
    await ctx.send(embed=embed)

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
