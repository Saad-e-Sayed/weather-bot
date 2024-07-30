import enum
import json
import logging
import os
import typing
import warnings

import dotenv
import telegram.ext

import api
import nlp

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)
warnings.filterwarnings(action="ignore", message=r".*CallbackQueryHandler", category=telegram.warnings.PTBUserWarning)

dotenv.load_dotenv()
with open('developer.json', 'rb') as fp:
    developer = telegram.User(**json.load(fp))

TOKEN = os.environ['BOT_TOKEN']
ReplyData = tuple[str, typing.Optional[telegram.TelegramObject], typing.Optional[telegram.constants.ParseMode]]


class State(enum.IntEnum):
    (query, ask, expecting_city) = range(3)


async def start(update: telegram.Update, _context: telegram.ext.ContextTypes.DEFAULT_TYPE) -> State:
    user = update.effective_user

    await update.message.reply_html(
        rf"Hi {user.mention_html()}!"
        "\nThis is Weather API bot. "
        "Usage is very simple, just type your query in plain English text and I will fetch the API for you. "
        "I depend on a simple Natural Language Processing technique which could fail sometimes."
        '\ne.g. "What is the current weather in New York?"'
        "\n\nAPI link: https://www.weatherapi.com/"
        f"\nDeveloper: {developer.mention_html('Saad Zahem')}",
        # reply_markup=telegram.ForceReply(selective=False),
    )
    return State.query


async def help_command(update: telegram.Update, _context: telegram.ext.ContextTypes.DEFAULT_TYPE) -> State:
    await update.message.reply_html(
        "Usage is very simple, just type your query in plain English text and I will fetch the API for you. "
        "I depend on a simple Natural Language Processing technique which could fail sometimes."
        '\ne.g. "What is the current weather in New York?"'
    )
    return State.query


async def raw(update: telegram.Update, _context: telegram.ext.ContextTypes.DEFAULT_TYPE) -> State:
    doc, outcome = nlp.parse(update.message.text)
    state = State.query
    reply_markup = None
    parse_mode = None

    if outcome is nlp.Outcome.weather_city:
        reply, reply_markup, parse_mode = get_weather_of_a_city(doc)

    elif outcome is nlp.Outcome.ask:
        intention = outcome.value.pop()
        text: str = '"%s"' % intention.value
        reply = f"Did you mean to ask for {text}? (reply yes/no)"
        state = State.ask

    else:
        if outcome is not nlp.Outcome.ambiguous:
            logger.fatal("Unexpected outcome %s, consider updating the code to handle the added types.")

        reply = ("Your query is ambiguous. "
                 "Try another format that matches better, "
                 "Or try /help for more information on how this bot works.")

    await update.message.reply_text(reply, reply_markup=reply_markup, parse_mode=parse_mode)
    return state


def get_weather_of_a_city(doc: nlp.spacy.tokens.Doc, default_reply_on_failure: str = '') -> ReplyData:
    try:
        city = nlp.extract_ent(doc, label='GPE').text
    except IndexError:
        # "Can you tell me about the current weather in a city?"
        # The user didn't mention any city
        # Instruct the user to mention the city in the next query
        reply = default_reply_on_failure or (
            "Sure, I can tell you about the weather condition in any city, "
            "just mention the city in your text.")
        reply_markup = None
        parse_mode = None
    else:
        reply, reply_markup, parse_mode = fetch_api(city)
    return reply, reply_markup, parse_mode


def fetch_api(city: str) -> ReplyData:
    resp = api.get(city)
    if resp.ok:
        data = api.APIData(resp.json())
        reply = str(data)
        parse_mode = telegram.constants.ParseMode.MARKDOWN_V2
        keyboard = build_keyboard(data)
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    else:
        reply = ("Something went wrong, "
                 "failed to fetch weather API. "
                 f"The API responded with status code {resp.status_code} '{resp.reason}'.")
        reply_markup = None
        parse_mode = None
    return reply, reply_markup, parse_mode


def build_keyboard(data: api.APIData) -> list[list[telegram.InlineKeyboardButton]]:
    sections = data.sections()
    del sections['location']  # first section (location) is not toggleable
    keyboard = []
    buttons = []

    for index, (method_name, active) in enumerate(reversed(list(sections.items()))):
        verb = 'Hide' if active else 'Show'
        section_name = data.normalize_section_name(method_name)
        text = f"{verb} {section_name}"
        button = telegram.InlineKeyboardButton(text, callback_data=data.toggle(method_name))

        if index // 2 > len(keyboard):
            keyboard.insert(0, buttons)
            buttons = []
        buttons.insert(0, button)
    keyboard.insert(0, buttons)
    return keyboard


async def button_clicked(update: telegram.Update, _context: telegram.ext.ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    toggle = typing.cast(api.ToggleSection, query.data)
    data = toggle()
    keyboard = build_keyboard(data)
    reply_markup = telegram.InlineKeyboardMarkup(keyboard)
    parse_mode = telegram.constants.ParseMode.MARKDOWN_V2
    await query.edit_message_text(text=str(data), reply_markup=reply_markup, parse_mode=parse_mode)


async def yes_no_answer(update: telegram.Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE) -> State:
    mo = context.matches.pop()
    answer = mo.group(1).lower()
    state = State.query

    if answer == 'yes':
        doc = nlp.nlp(update.effective_message.text)
        reply = "Please specify the city in the next message."
        returned_reply, reply_markup, parse_mode = get_weather_of_a_city(doc, default_reply_on_failure=reply)
        if returned_reply == reply:
            state = State.expecting_city
        reply = returned_reply
    else:
        # answer was no
        reply = "Please try another query."
        reply_markup = None
        parse_mode = None

    await update.message.reply_text(reply, reply_markup=reply_markup, parse_mode=parse_mode)
    return state


async def take_city(update: telegram.Update, context: telegram.ext.ContextTypes.DEFAULT_TYPE) -> State:
    doc, ent = context.args
    reply, reply_markup, parse_mode = fetch_api(ent.text)
    await update.message.reply_text(reply, reply_markup=reply_markup, parse_mode=parse_mode)
    return State.query


class NamedEntityFilter(telegram.ext.filters.MessageFilter):
    __slots__ = ("label",)

    def __init__(self, label: str):
        self.label: str = label
        super().__init__(name=f"NamedEntityFilter({self.label})", data_filter=True)

    def filter(self, message: telegram.Message) -> typing.Optional[typing.Dict[str, typing.List[typing.Match[str]]]]:
        if message.text:
            doc = nlp.nlp(message.text)
            try:
                ent = nlp.extract_ent(doc, self.label)
                return {"args": [doc, ent]}
            except IndexError:
                pass
        return {}


start_command_handler = telegram.ext.CommandHandler('start', start)
help_command_handler = telegram.ext.CommandHandler('help', help_command)

raw_message_handler = telegram.ext.MessageHandler(telegram.ext.filters.TEXT & ~telegram.ext.filters.COMMAND, raw)
yesno_message_handler = telegram.ext.MessageHandler(telegram.ext.filters.Regex('((?i)yes|no)'), yes_no_answer)
gpe_message_handler = telegram.ext.MessageHandler(NamedEntityFilter('GPE'), take_city)

toggle_button_handler = telegram.ext.CallbackQueryHandler(button_clicked)

conv_handler = telegram.ext.ConversationHandler(
    entry_points=[start_command_handler, help_command_handler],
    states={
        State.query: [raw_message_handler],
        State.ask: [yesno_message_handler, raw_message_handler],
        State.expecting_city: [gpe_message_handler],
    },
    fallbacks=[start_command_handler, help_command_handler, toggle_button_handler],
    name="weatherbot_conversation",
    persistent=True,
)


def main() -> None:
    persistence = telegram.ext.PicklePersistence(filepath='weatherbot.pkl')
    application = (
        telegram.ext.Application.builder()
        .token(TOKEN)
        .persistence(persistence)
        .arbitrary_callback_data(True)
        .build()
    )
    application.add_handler(toggle_button_handler)
    application.add_handler(conv_handler)
    application.run_polling()


if __name__ == '__main__':
    main()
