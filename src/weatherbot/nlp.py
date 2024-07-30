import enum

import spacy.tokens

nlp = spacy.load('en_core_web_md')


class Outcome(enum.Enum):
    weather_city = 'current weather in a city'
    ambiguous = None
    ask = []  # mutable value, intended for holding another enum member as a value


def parse(text: str) -> tuple[spacy.tokens.Doc, Outcome]:
    doc = nlp(text)
    most_likely = [0, Outcome.ask]

    for enum_member in Outcome.__members__.values():
        if type(enum_member.value) is not str:
            if most_likely[1].value.__len__() == 0:
                return doc, Outcome.ambiguous
            else:
                return doc, most_likely[1]

        matching_stmt = nlp(enum_member.value)
        scale = doc.similarity(matching_stmt)
        similarity = round(scale * 100)

        if similarity >= 65:
            return doc, enum_member

        if similarity >= 50 and similarity > most_likely[0]:
            most_likely[0] = similarity
            most_likely[1].value.clear()
            most_likely[1].value.append(enum_member)


def extract_ent(doc: spacy.tokens.Doc, label: str) -> spacy.tokens.Span:
    """Extracts the first entity that has the given label in the document, raises IndexError if no entity was found"""
    return [ent for ent in doc.ents if ent.label_ == label][0]
