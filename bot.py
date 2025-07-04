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

# ───── Constants ─────
CHOSUNG_LIST = [chr(code) for code in range(ord('ㄱ'), ord('ㅎ') + 1)]

def get_chosung(text: str) -> str:
    """한글 문자열을 초성 문자열로 변환합니다. 예: '가위바위보' -> 'ㄱㅂㅂ'"""
    def is_hangul(char):
        return '가' <= char <= '힣'
    
    result = ''
    for char in text:
        if not is_hangul(char):
            result += char
            continue
        code = ord(char) - ord('가')
        chosung_index = code // 588
        result += CHOSUNG_LIST[chosung_index]
    return result

# ───── 초성 → 명령어 매핑 ─────
초성명령어 = {
    "ㅊㅅ": "출석",
    "ㅍㅇㅌ": "포인트",
    "ㄹㅋ": "랭킹",
    "ㄷㅂ": "도박",
    "ㅅㄹ": "슬롯",
    "ㅂㄴㄱ": "보내기",
    "ㅈㄱ": "지급",
    "ㄱㅁ": "경마",
    "ㄱㅂㅂ": "가위바위보",
    "ㅂㅇ": "반응속도",
    "ㅅㅈ": "숫자게임"
}

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
    "inventory": {},
    "user_join_times": {},         
    "user_mic_history": {} 
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
    match = re.search(r"\((.*?)\)\s*(\d+)", args)
    if not match:
        return None, None
    name = match.group(1).strip()
    price = int(match.group(2))
    return name, price

# ───── 버튼 설정 ─────
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("❗ BOT_TOKEN 환경변수가 설정되지 않았습니다.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ───── 음성 접속 포인트 적립 설정 ─────
POINT_RATE = {"on": 2, "off": 1}          # 1분당 적립 포인트
user_join_times: dict[str, datetime.datetime] = {}
user_mic_history: dict[str, list[tuple[datetime.datetime, bool]]] = {}

def save_username(member: discord.Member):
    """닉네임 변경 시 기록 (선택: 이미 처리 중이면 제거)"""
    data = read_data()
    uid = str(member.id)
    data.setdefault("usernames", {})[uid] = member.display_name
    write_data(data)

def process_voice_leave(uid: str, leave_time: datetime.datetime):
    """채널을 완전히 떠나거나 이동할 때 호출 – 머무른 시간만큼 포인트 계산"""
    join_time = user_join_times.pop(uid, None)
    history   = user_mic_history.pop(uid, [])

    if not join_time:
        return  # 비정상 종료 보호

    history.append((leave_time, history[-1][1] if history else False))

    # join_time 이후 구간만 남김
    history = [(t, m) for t, m in history if t >= join_time]

    total_minutes = 0.0
    for (t1, mic_on1), (t2, _) in zip(history, history[1:]):
        mins = (t2 - t1).total_seconds() / 60
        total_minutes += mins * (POINT_RATE["on"] if mic_on1 else POINT_RATE["off"])

    earned = int(total_minutes)  # 소수점 버림

    if earned > 0:
        data = read_data()
        data["user_points"][uid]  = data["user_points"].get(uid, 0)  + earned
        data["activity_xp"][uid]  = data["activity_xp"].get(uid, 0)  + earned
        write_data(data)

# ───── 음성 상태 이벤트 ─────
@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    uid = str(member.id)

    # ✅ TTS 봇 제외
    if uid in ['1241383865478807582', '1289824359002669126']:
        return

    now = datetime.datetime.utcnow()
    save_username(member)

    prev_channel = before.channel
    curr_channel = after.channel

    # 1) 채널 입장
    if not prev_channel and curr_channel:
        user_join_times[uid]   = now
        user_mic_history[uid]  = [(now, not after.self_mute)]

    # 2) 같은 채널 내에서 mute/unmute 토글
    elif prev_channel and curr_channel and prev_channel.id == curr_channel.id:
        user_mic_history.setdefault(uid, []).append((now, not after.self_mute))

    # 3) 채널 이동
    elif prev_channel and curr_channel and prev_channel.id != curr_channel.id:
        process_voice_leave(uid, now)
        user_join_times[uid]   = now
        user_mic_history[uid]  = [(now, not after.self_mute)]

    # 4) 채널 퇴장
    elif prev_channel and not curr_channel:
        process_voice_leave(uid, now)

# ───── 초성 명령어 처리 이벤트 ─────
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if message.content.startswith("!"):
        cmd_only = message.content.split()[0][1:]
        full_cmd = 초성명령어.get(cmd_only)
        if full_cmd:
            message.content = message.content.replace(f"!{cmd_only}", f"!{full_cmd}", 1)

    await bot.process_commands(message)

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
    bonus = 77 if random.random() < 0.05 else 0  # 5% 확률로 77포인트, 아니면 0
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

    # 보너스 메시지 추가
    bonus_msg = ""
    if bonus == 77:
        bonus_msg = (
            f"@{ctx.author.display_name}님의 출석이 메카살인기의 심장을 깨워\n"
            f"🎉 대박! 추가로 **{bonus}포인트**를 획득했습니다!"
        )

    # 임베드로 출력
    embed = discord.Embed(
        title=f"**{ctx.author.display_name} 님 출석 완료!**",
        description=(
            f"• 📅 출석 보상 : **{base_reward}포인트** 지급\n"
            f"• 🏃🏻 누적 출석 {total_checkins}일, 연속 {data['streak_log'][uid]}일"
        ),
        color=discord.Color.green()
    )

    if bonus_msg:
        embed.add_field(name="💥 출석 보너스", value=bonus_msg, inline=False)

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
ALLOWED_ADMIN_IDS = ['518697602774990859', '1335240110358265967']  # 문자열로 저장

@bot.command(name='초기화')
async def reset_data(ctx):
    if str(ctx.author.id) not in ALLOWED_ADMIN_IDS:
        await ctx.send("⛔ 이 명령은 관리자만 사용할 수 있습니다.")
        return

    global data
    data = DEFAULT_DATA.copy()
    write_data(data)
    await ctx.send("✅ 데이터가 초기화되었습니다.")

@bot.command()
async def 지급(ctx, member: discord.Member, 점수: int):
    if str(ctx.author.id) not in ALLOWED_ADMIN_IDS:
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
    embed.add_field(
        name="🎮 미니게임 안내", 
        value="`!미니게임 도움말`을 입력해 다양한 미니게임 기능을 확인해보세요!", 
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
@bot.command()
async def 재능상점(ctx, action=None, seller: discord.Member = None, *, args=None):
    user_id = str(ctx.author.id)
    store = load_talent_store()

    # ── 등록 ──
    if action == "등록":
        if seller and seller.id != ctx.author.id:
            return await ctx.send("❌ 다른 사람 대신 상품을 등록할 수 없습니다. 본인만 등록 가능해요.")

        # 판매자 없이 입력한 경우 → 본인으로 간주
        if not args:
            return await ctx.send("❗ 등록 형식: `!재능상점 등록 (상품명) 가격`")

        name, price = extract_name_and_price(args)
        if not name or price is None:
            return await ctx.send("❗ 상품명은 `( )` 안에, 가격은 숫자로 입력해 주세요.")

        store.setdefault(user_id, {"items": []})["items"].append({"name": name, "price": price})
        save_talent_store(store)
        await ctx.send(f"✅ 상품 '**{name}**'이 등록되었습니다. 가격: {price}코인")

    # ── 관리 ──
    elif action == "관리":
        if user_id not in store or not store[user_id]["items"]:
            return await ctx.send("📦 등록된 상품이 없습니다.")

        if args and args.endswith(" 삭제"):
            m = re.search(r"\((.*?)\)", args)
            if not m:
                return await ctx.send("❗ 삭제 형식: `!재능상점 관리 (상품명) 삭제`")
            target = m.group(1).strip()
            before = len(store[user_id]["items"])
            store[user_id]["items"] = [it for it in store[user_id]["items"] if it["name"] != target]
            save_talent_store(store)
            return await ctx.send(
                f"🗑️ {'삭제 완료!' if len(store[user_id]['items']) < before else '해당 상품이 없습니다.'}"
            )

        embed = discord.Embed(title="🗂️ 내 상점 상품 목록", color=discord.Color.blue())
        lines = [f"{i+1}. **{it['name']}** — {it['price']}코인"
                 for i, it in enumerate(store[user_id]["items"])]
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    # ── 구경 ──
    elif action == "구경":
        if not store:
            return await ctx.send("📭 현재 등록된 상점이 없습니다.")

        embed = discord.Embed(title="🛍️ 전체 재능상점 목록", color=discord.Color.green())
        count = 1

        for sid, info in store.items():
            member = ctx.guild.get_member(int(sid))
            if not member or not info['items']:
                continue
            for item in info['items']:
                embed.add_field(
                    name=f"{count}. **{item['name']}**",
                    value=(
                        f"• 👤 판매자: {member.display_name}\n"
                        f"• 💰 가격: {item['price']}코인"
                    ),
                    inline=False
                )
                count += 1

        if count == 1:
            return await ctx.send("📭 현재 등록된 상품이 없습니다.")
        await ctx.send(embed=embed)

     # ── 구매 ──
    elif action == "구매":
        if not seller or not args:
            return await ctx.send("❗ 형식: `!재능상점 구매 @판매자 (상품명)`")

        m = re.search(r"\((.*?)\)", args)
        if not m:
            return await ctx.send("❗ 상품명을 괄호 `(상품명)` 형태로 입력해 주세요.")
        item_name = m.group(1).strip()

        seller_id = str(seller.id)
        if seller_id not in store or not store[seller_id]["items"]:
            return await ctx.send("❌ 판매자의 상점이 비어 있습니다.")

        item = next((it for it in store[seller_id]["items"] if it["name"] == item_name), None)
        if not item:
            return await ctx.send(f"❌ '{item_name}' 상품이 없습니다.")

        data = read_data()
        buyer_id = str(ctx.author.id)
        price = item["price"]

        if data["user_points"].get(buyer_id, 0) < price:
            return await ctx.send("😢 포인트가 부족합니다.")

        data["user_points"][buyer_id] -= price
        data["user_points"][seller_id] = data["user_points"].get(seller_id, 0) + price
        write_data(data)

        await ctx.send(f"✅ {ctx.author.display_name}님이 {seller.display_name}님의 '**{item_name}**' 상품을 {price}코인에 구매했습니다!")

        try:
            dm = discord.Embed(
                title="**📬 재능상점 구매 알림**",
                description=(
                    f"🛍️ {ctx.author.display_name}님이 '**{item_name}**'을(를) **{price}코인**에 구매했습니다!\n"
                    f"구체적인 내용은 {ctx.author.mention}님과 이야기를 나눠보세요!"
                ),
                color=discord.Color.purple()
            )
            await seller.send(embed=dm)
        except discord.Forbidden:
            await ctx.send("⚠️ 판매자에게 DM을 보낼 수 없습니다 (DM 차단).")

    # ── 도움말 ──
    elif action == "도움말":
        embed = discord.Embed(
            title="🌞 솔라 재능상점 도움말",
            description="재능상점은 솔라리스 클랜원들의 다양한 재능을 \n포인트로 사고 파는 거래 시스템입니다.",
            color=0x00ffcc
        )
        embed.set_thumbnail(url=ctx.bot.user.avatar.url)
        embed.add_field(
            name="🛒 상품 등록 (본인만 가능)",
            value="`!재능상점 등록 @판매자 (상품명) 가격`\n예: `!재능상점 등록 @판매자 (썸네일 제작) 30`",
            inline=False
        )
        embed.add_field(
            name="📦 내 상점 관리/삭제",
            value="`!재능상점 관리`\n`!재능상점 관리 @판매자 (상품명) 삭제`",
            inline=False
        )
        embed.add_field(
            name="🛍️ 전체 상품 구경",
            value="`!재능상점 구경`",
            inline=False
        )
        embed.add_field(
            name="🎯 상품 구매",
            value="`!재능상점 구매 @판매자 (상품명)`\n예: `!재능상점 구매 @희카츄/97 (썸네일 제작)`",
            inline=False
        )
        embed.add_field(
            name="⚠️ 참고사항",
            value="• 등록은 본인만 가능하며 @멘션 ❌\n• 구매 시에만 @멘션 필요 ✅\n• 상품명은 반드시 괄호 `( )` 안에 작성",
            inline=False
        )
        await ctx.send(embed=embed)

    # ── 잘못된 입력 ──
    else:
        await ctx.send(
            "**사용법 요약:**\n"
            "`!재능상점 등록 @판매자 (상품명) 가격`\n"
            "`!재능상점 관리 @판매자 [(상품명) 삭제]`\n"
            "`!재능상점 구경`\n"
            "`!재능상점 구매 @판매자 (상품명)`\n"
            "`!재능상점 도움말`"
        )

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

# ───────────경마 게임 ──────────────
TRACK_LEN = 25
TICK_SEC  = 0.25
REFRESH_EVERY = 1
HORSE_ICONS = ["🏇", "🐂", "🐉", "🦓", "🐐", "🐖", "🐪"]

horse_race_state = {
    "horses": [],
    "positions": [],
    "is_running": False,
    "bettors": {},    # {uid: (horse_idx, amount)}
    "pool": 0,
    "msg": None
}

@bot.command()
async def 경마(ctx, action: str = None, *, args: str | None = None):
    """!경마 입장 / 시작 / 종료"""
    # ─── 입장 ───
    if action == "입장":
        if horse_race_state["is_running"]:
            return await ctx.send("🚫 이미 경주가 진행 중입니다.")
        if not args:
            return await ctx.send("❗ 형식: `!경마 입장 말1 말2 ...` (2~8마리)")
        horses = args.split()
        if not 2 <= len(horses) <= 8:
            return await ctx.send("❗ 말은 2~8마리만 등록 가능합니다.")
        horse_race_state.update({
            "horses": horses,
            "positions": [0]*len(horses),
            "bettors": {},
            "pool": 0,
            "is_running": False,
            "msg": None
        })
        embed = Embed(title="🏇 경마가 준비되었습니다!", color=0xF1C40F)
        embed.description = "말 번호와 금액으로 배팅하세요: `!배팅 <번호> <포인트>`\n\n" + "\n".join(
            f"**{i+1}.** {name}" for i, name in enumerate(horse_race_state["horses"])
        )
        return await ctx.send(embed=embed)

    # ─── 시작 ───
    if action == "시작":
        if not horse_race_state["horses"]:
            return await ctx.send("❗ 먼저 `!경마 입장`으로 말을 등록해주세요.")
        if horse_race_state["is_running"]:
            return await ctx.send("🚫 이미 경주가 시작되었습니다.")

        horse_race_state["is_running"] = True
        track_msg = await ctx.send("```🌾 경기 시작 준비 중...```")
        horse_race_state["msg"] = track_msg

        momentums = [random.uniform(0.8, 1.2) for _ in horse_race_state["horses"]]
        finished, order, tick = set(), [], 0

        while True:
            await asyncio.sleep(TICK_SEC)
            tick += 1
            for idx in range(len(horse_race_state["positions"])):
                if idx in finished:
                    continue
                condition = random.uniform(0.9, 1.1) * momentums[idx]
                weights = [1*condition, 2.5, 3.5*(2-condition), 1.5]
                step = random.choices([0,1,2,3], weights=weights)[0]
                horse_race_state["positions"][idx] += step
                if horse_race_state["positions"][idx] >= TRACK_LEN:
                    finished.add(idx)
                    order.append(idx)

            if tick % REFRESH_EVERY == 0 or len(finished)==len(horse_race_state["horses"]):
                lines=[]
                for i,(name,pos) in enumerate(zip(horse_race_state["horses"],horse_race_state["positions"])):
                    icon = HORSE_ICONS[i%len(HORSE_ICONS)]
                    bar  = "."*min(pos,TRACK_LEN)+icon+"."*(TRACK_LEN-min(pos,TRACK_LEN))
                    lines.append(f"{i+1}|{bar[:TRACK_LEN]}| {name}")
                await track_msg.edit(content="```\n"+"\n".join(lines)+"\n```")
            if len(finished)==len(horse_race_state["horses"]):
                break

        medals=["🥇","🥈","🥉"]
        horses=horse_race_state["horses"]
        result_lines=[f"{medals[r]} {horses[h]}" if r<3 else f"{r+1}등 {horses[h]}" for r,h in enumerate(order)]
        pool   = horse_race_state["pool"]
        bettors= horse_race_state["bettors"]
        winner_hidx=order[0]
        owner_id = next((uid for uid,(idx,amt) in bettors.items() if idx==winner_hidx), None)
        if pool and owner_id:
            data=read_data()
            data["user_points"][owner_id]=data["user_points"].get(owner_id,0)+pool
            write_data(data)
            payout=f"🎉 우승 말: {horses[winner_hidx]}\n💰 총 배팅액 {pool}포인트를 <@{owner_id}>님이 가져갑니다!"
        elif pool:
            payout="💸 배팅이 있었지만 우승 말에 배팅한 유저가 없습니다."
        else:
            payout="😔 배팅 없이 진행되었습니다."
        embed=Embed(title="🏁 경기 종료 결과",color=0x9B59B6)
        embed.description="\n".join(result_lines)
        embed.add_field(name="📢 배팅 결과",value=payout,inline=False)
        await ctx.send(embed=embed)
        horse_race_state.update({"horses":[],"positions":[],"bettors":{},"pool":0,"is_running":False,"msg":None})
        return

    # ─── 종료 ───
    if action == "종료":
        horse_race_state.update({"horses":[],"positions":[],"bettors":{},"pool":0,"is_running":False,"msg":None})
        return await ctx.send("😕 경마가 강제 종료되었습니다.")

    await ctx.send("❗ 사용법: `!경마 입장 ...`, `!경마 시작`, `!경마 종료`")

# ─── 배팅 명령어 ───
@bot.command(name="배팅")
async def 배팅(ctx, 번호: int=None, 금액: int=None):
    if not horse_race_state["horses"]:
        return await ctx.send("❗ 먼저 말을 등록해주세요: `!경마 입장 ...`")
    if horse_race_state["is_running"]:
        return await ctx.send("🚫 이미 경주가 시작되어 배팅할 수 없습니다.")
    if 번호 is None or 금액 is None:
        return await ctx.send("❗ 형식: `!배팅 <번호> <포인트>`")
    if not 1<=번호<=len(horse_race_state["horses"]):
        return await ctx.send("❗ 유효한 말 번호를 입력해주세요.")
    uid=str(ctx.author.id)
    data=read_data()
    if data["user_points"].get(uid,0)<금액:
        return await ctx.send("😭 보유 포인트가 부족합니다.")
    if uid in horse_race_state["bettors"]:
        return await ctx.send("⚠️ 이미 배팅했습니다.")
    # 포인트 차감 및 기록
    data["user_points"][uid]-=금액
    horse_race_state["bettors"][uid]=(번호-1,금액)
    horse_race_state["pool"]+=금액
    write_data(data)
    await ctx.send(f"💸 {ctx.author.display_name}님이 {번호}번 말에 {금액}포인트 배팅!")

# ───── 숫자게임 ─────
@bot.command()
async def 숫자게임(ctx):
    target = random.randint(1, 10)
    await ctx.send("🎲 1부터 10 사이의 숫자를 맞혀보세요! (10초 안에 채팅으로 입력)")

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        msg = await bot.wait_for('message', check=check, timeout=10.0)
        guess = int(msg.content)

        if guess == target:
            data = read_data()
            uid = str(ctx.author.id)
            data["user_points"][uid] = data["user_points"].get(uid, 0) + 50
            write_data(data)
            await ctx.send(f"🎉 정답입니다! 숫자는 {target}이었어요.\n💰 보상으로 50코인을 획득하셨습니다!")
        else:
            await ctx.send(f"❌ 틀렸어요! 정답은 {target}이었습니다.")
    except asyncio.TimeoutError:
        await ctx.send(f"⌛ 시간이 초과되었습니다! 정답은 {target}이었습니다.")
    except ValueError:
        await ctx.send("❗ 숫자만 입력해 주세요.")

# ──────────────────── 공통 데이터 ────────────────────
RESULT_TXT = ["무승부!", "패배...", "승리!"]  # (user - rival) % 3 => 0무 1패 2승

# ──────────────────── !미니게임 도움말 ────────────────────
@bot.command(name="미니게임", aliases=["미니게임도움말", "미니게임 도움말"])
async def 미니게임도움말(ctx):
    embed = Embed(title="🎮 미니게임 도움말", color=discord.Color.teal())
    embed.add_field(name="🏇 경마 게임", value="`!경마` → 1등 말에 배팅한 유저가 모든 포인트를 가져갑니다!", inline=False)
    embed.add_field(name="✊ 가위바위보 봇전", value="`!가위바위보 [가위|바위|보]` → 봇과 대결 (승리 시 포인트 획득)", inline=False)
    embed.add_field(name="⚔️ 가위바위보 대결", value="`!가위바위보대결 @상대` → 유저와 1:1 대결", inline=False)
    embed.add_field(name="⚡ 반응속도 배틀", value="`!반응속도 [배팅액]` → 가장 빠르게 입력한 유저가 포인트 독식!", inline=False)
    embed.add_field(name="🎲 주사위 게임", value="`!주사위` → 주사위 숫자 승부! 이기면 보상 획득", inline=False)
    embed.add_field(name="🎯 숫자 게임", value="`!숫자게임` → 1~10 사이 숫자를 맞춰서 100포인트 획득!", inline=False)
    await ctx.send(embed=embed)

# ──────────────────── 미니게임 1) 가위바위보 봇전 (봇 vs 유저) ────────────────────
@bot.command()
async def 가위바위보(ctx, 선택: str | None = None, 포인트: int | None = 10):
    if 선택 not in CHOICES:
        return await ctx.send("❗ 형식: `!가위바위보 가위|바위|보 [포인트]`")

    uid = str(ctx.author.id)
    data = read_data()
    if data["user_points"].get(uid, 0) < 포인트:
        return await ctx.send("😭 포인트가 부족합니다.")

    bot_choice = random.choice(list(CHOICES.keys()))
    result = (CHOICES[선택] - CHOICES[bot_choice]) % 3
    if result == 2:
        data["user_points"][uid] += 포인트
    elif result == 1:
        data["user_points"][uid] -= 포인트
    write_data(data)

    color = 0x2ecc71 if result == 2 else 0xe74c3c if result == 1 else 0x95a5a6
    embed = Embed(title="✊ 가위바위보 결과", color=color)
    embed.description = (
        f"당신: **{선택}**  vs  봇: **{bot_choice}**\n"
        f"결과: **{RESULT_TXT[result]}**\n"
        f"현재 보유 포인트: {data['user_points'][uid]}"
    )
    await ctx.send(embed=embed)

# ──────────────────── 미니게임 2) 가위바위보 대결 (유저 vs 유저) ─────────────────
CHOICES = {"가위": 0, "바위": 1, "보": 2}

@bot.command(name="가위바위보대결")
async def 가위바위보대결(ctx, 상대: discord.Member = None):
    if not 상대 or 상대.bot:
        return await ctx.send("❗ 형식: `!가위바위보대결 @상대`")
    if 상대 == ctx.author:
        return await ctx.send("❗ 자기 자신과는 대결할 수 없습니다.")

    await ctx.send(
        f"<@{상대.id}>! {ctx.author.mention}님이 가위바위보 대결을 신청했습니다.\n"
        f"수락하려면 `!수락`을 입력해주세요. (30초 이내)"
    )

    def 수락체크(m):
        return m.author == 상대 and m.content.strip() == "!수락" and m.channel == ctx.channel

    try:
        await bot.wait_for("message", timeout=30.0, check=수락체크)
    except asyncio.TimeoutError:
        return await ctx.send("⌛ 상대가 수락하지 않아 대결이 취소되었습니다.")

    await ctx.send(f"💰 배팅 금액을 입력해주세요 (예: `!배팅금 50`) — 제한 시간 15초")

    배팅액 = 10

    def 배팅체크(m):
        return m.author == ctx.author and m.content.startswith("!배팅금") and m.channel == ctx.channel

    try:
        msg = await bot.wait_for("message", timeout=15.0, check=배팅체크)
        parts = msg.content.split()
        if len(parts) == 2 and parts[1].isdigit():
            배팅액 = int(parts[1])
        else:
            return await ctx.send("❗ 올바른 형식으로 입력해주세요: `!배팅금 50`")
    except asyncio.TimeoutError:
        return await ctx.send("⌛ 배팅 입력 시간이 초과되어 대결이 취소됩니다.")

    # 포인트 차감 처리
    data = read_data()
    for user in (ctx.author, 상대):
        uid = str(user.id)
        if data["user_points"].get(uid, 0) < 배팅액:
            return await ctx.send(f"😭 {user.display_name}님의 포인트가 부족합니다.")
        data["user_points"][uid] -= 배팅액
    write_data(data)

    await asyncio.sleep(3)
    await ctx.send("✊✌️🖐️ 지금! `가위`, `바위`, `보` 중 하나를 입력하세요! (5초 이내)")

    picks = {}

    def 선택체크(m):
        return m.author in (ctx.author, 상대) and m.content.strip() in CHOICES and m.channel == ctx.channel

    end_time = asyncio.get_event_loop().time() + 5
    while len(picks) < 2 and asyncio.get_event_loop().time() < end_time:
        try:
            msg = await bot.wait_for("message", timeout=end_time - asyncio.get_event_loop().time(), check=선택체크)
            picks[msg.author.id] = msg.content.strip()
        except asyncio.TimeoutError:
            break

    a_pick = picks.get(ctx.author.id)
    b_pick = picks.get(상대.id)

    if not a_pick or not b_pick:
        forfeiter = 상대 if not b_pick else ctx.author
        winner = ctx.author if forfeiter == 상대 else 상대
        uid = str(winner.id)
        data = read_data()
        data["user_points"][uid] = data["user_points"].get(uid, 0) + 배팅액 * 2
        write_data(data)
        return await ctx.send(
            f"🏃‍♀️ {forfeiter.display_name}님이 입력하지 않아 자동 패배!\n"
            f"{winner.display_name}님이 배팅액 {배팅액 * 2}포인트를 전부 가져갑니다!"
        )

    diff = (CHOICES[a_pick] - CHOICES[b_pick]) % 3
    winner = None
    if diff == 0:
        result_msg = "무승부! 포인트 반환"
        data = read_data()
        for user in (ctx.author, 상대):
            uid = str(user.id)
            data["user_points"][uid] = data["user_points"].get(uid, 0) + 배팅액
        write_data(data)
    elif diff == 1:
        winner = ctx.author
        result_msg = f"🏆 {ctx.author.display_name}님 승리! 배팅액 {배팅액 * 2}포인트를 전부 가져갑니다!"
    else:
        winner = 상대
        result_msg = f"🏆 {상대.display_name}님 승리! 배팅액 {배팅액 * 2}포인트를 전부 가져갑니다!"

    if winner:
        uid = str(winner.id)
        data = read_data()
        data["user_points"][uid] = data["user_points"].get(uid, 0) + 배팅액 * 2
        write_data(data)

    embed = Embed(title="✂️ 가위바위보 대결 결과", color=discord.Color.blue())
    embed.description = (
        f"{ctx.author.display_name}: **{a_pick}**  vs  {상대.display_name}: **{b_pick}**\n\n"
        f"{result_msg}"
    )
    await ctx.send(embed=embed)


# ──────────────────── 미니게임 3) 반응속도 배틀 (1:N 전용) ────────────────────
@bot.command(name="반응속도")
async def 반응속도(ctx, 베팅: int = 10):
    # ───── ① 안내 메시지 ─────
    await ctx.send(
        f"⚡ **반응속도 배틀** 시작!\n"
        f"배팅액: **{베팅}포인트**\n"
        f"30초 동안 `!참가` 로 참여하세요!\n"
        f"▶ 충분히 모이면 방장(`{ctx.author.display_name}`)이 `!시작`을 입력해 바로 시작할 수 있습니다."
    )

    # ───── ② 참가자 초기화 (방장은 자동 참가) ─────
    participants: dict[int, str] = {ctx.author.id: ctx.author.display_name}

    # 참가‧시작 메시지 판별 함수
    def wait_check(m: discord.Message) -> bool:
        return (
            m.channel == ctx.channel
            and not m.author.bot
            and m.content.strip() in ("!참가", "!시작")
        )

    # ───── ③ 30초 또는 방장 !시작 입력까지 대기 ─────
    end_time = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < end_time:
        try:
            msg: discord.Message = await bot.wait_for(
                "message",
                timeout=end_time - asyncio.get_event_loop().time(),
                check=wait_check,
            )

            content = msg.content.strip()

            # ③-A 참가 처리
            if content == "!참가":
                if msg.author.id not in participants:
                    participants[msg.author.id] = msg.author.display_name
                    await ctx.send(f"✅ **{msg.author.display_name}** 님 참가 완료! (현재 {len(participants)}명)")

            # ③-B 즉시 시작 처리 (방장만 허용)
            elif content == "!시작" and msg.author == ctx.author:
                if len(participants) < 2:
                    await ctx.send("❗ 최소 2명이 있어야 시작할 수 있습니다!")
                else:
                    await ctx.send("⏩ 방장이 시작을 눌렀습니다. 바로 게임을 시작합니다!")
                    break

        except asyncio.TimeoutError:
            break  # 30초 만료

    # ───── ④ 참가 인원 확인 ─────
    if len(participants) < 2:
        return await ctx.send("❗ 2명 이상 참가해야 합니다. 게임이 취소되었습니다.")

    # ───── ⑤ 베팅 포인트 차감 ─────
    data = read_data()
    for uid in participants:
        if data["user_points"].get(str(uid), 0) < 베팅:
            return await ctx.send(f"😭 {participants[uid]}님의 포인트가 부족합니다!")
        data["user_points"][str(uid)] -= 베팅
    write_data(data)

    # ───── ⑥ 본게임: '솔라리스' 입력 속도 측정 ─────
    await ctx.send("준비... 키보드에 손을 올려 주세요!")
    await asyncio.sleep(random.uniform(2, 5))  # 랜덤 대기
    await ctx.send("✨ **지금!** `솔라리스` 를 가장 빠르게 입력!")

    start = time.perf_counter()
    times: dict[int, float] = {}

    def reaction_check(m: discord.Message) -> bool:
        return (
            m.channel == ctx.channel
            and m.content.strip() == "솔라리스"
            and m.author.id in participants
        )

    while len(times) < len(participants):
        try:
            msg: discord.Message = await bot.wait_for("message", timeout=5.0, check=reaction_check)
            if msg.author.id not in times:  # 첫 반응만 기록
                times[msg.author.id] = round(time.perf_counter() - start, 3)
        except asyncio.TimeoutError:
            break

    # ───── ⑦ 결과 집계 ─────
    if not times:
        # 아무도 입력 안 하면 환불
        for uid in participants:
            data["user_points"][str(uid)] += 베팅
        write_data(data)
        return await ctx.send("⌛ 아무도 입력하지 않아 게임이 무효가 되었습니다. 포인트를 환불했습니다.")

    winner_id = min(times, key=times.get)               # 가장 짧은 시간
    pot = 베팅 * len(participants)                      # 총 상금
    data["user_points"][str(winner_id)] += pot          # 상금 지급
    write_data(data)

    # 랭킹 문자열 생성
    ranking = sorted(times.items(), key=lambda x: x[1])
    result_txt = "\n".join([f"{i+1}등 : <@{uid}>  {t}s" for i, (uid, t) in enumerate(ranking)])

    # ───── ⑧ 결과 메시지 Embed ─────
    embed = Embed(title="⚡ 반응속도 배틀 결과", color=discord.Color.gold())
    embed.description = (
        f"🏆 **1등 <@{winner_id}>**, 총 상금 **{pot}포인트** 획득!\n\n"
        f"{result_txt}"
    )
    await ctx.send(embed=embed)

# ───── 주사위 게임 ─────
@bot.command(name="주사위")
async def 주사위(ctx):
    uid = str(ctx.author.id)
    data = read_data()

    if data["user_points"].get(uid, 0) < 10:
        return await ctx.send("❗ 최소 10포인트가 필요합니다.")

    player_roll = random.randint(1, 6)
    bot_roll = random.randint(1, 6)

    result_msg = ""
    if player_roll > bot_roll:
        data["user_points"][uid] += 30
        result_msg = f"🎉 주사위 승리! +30포인트\n"
    elif player_roll < bot_roll:
        data["user_points"][uid] -= 10
        result_msg = f"😢 주사위 패배... -10포인트\n"
    else:
        result_msg = "🤝 주사위 무승부! 포인트 변동 없습니다~"

    write_data(data)

    embed = Embed(title="🎲 주사위 대결", color=discord.Color.green())
    embed.description = (
        f"당신 🎲: {player_roll}  vs  봇 🎲: {bot_roll}\n\n"
        f"{result_msg}현재 포인트: {data['user_points'][uid]}"
    )
    await ctx.send(embed=embed)

# ───── 봇 실행 ─────
print("🤖 디스코드 봇 메카살인기 실행 준비 완료!")
bot.run(TOKEN)