"""Вычищает секреты (API-ключи поставщиков) из текста перед тем, как он
попадёт в исключение/лог/ответ пользователю.

АвтоЕвро передаёт ключ прямо в пути URL, Москворечье — логин/пароль в
query-параметрах (см. autoeuro_client.py/moskvorechye_client.py — так
устроен протокол самих поставщиков, это не наша прихоть, поэтому просто
"не класть ключ в URL" не вариант). requests/urllib3 при сетевой ошибке
(таймаут, отказ соединения) включают в текст исключения ПОЛНЫЙ URL запроса
(с ключом) — эта строка форматируется в AutoEuroError/MoskvorechyeError и
дальше либо попадает в лог (logger.warning в parts_supplier_client.py), либо
идёт как есть в ответ фронту (search_all — ошибку намеренно не глотаем, см.
её докстринг), то есть ключ в обоих случаях виден за пределами кода,
который его использует."""

from __future__ import annotations


def redact_secrets(text: str, secrets: list[str | None]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text
