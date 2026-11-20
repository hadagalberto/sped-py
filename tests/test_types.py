from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from sped.core.types import Field, FieldDef, Record, RegisterDef


def test_coerce_decimal_and_integer() -> None:
    money = FieldDef(1, "VL_ITEM", "N", 10, False, 2)
    # C2: Guia Prático EFD ICMS/IPI — corpo inteiro não sofre escalamento;
    # "10000" em N(10,2) vale 10000,00, não 100,00.
    assert money.coerce("10000") == Decimal("10000.00")
    assert money.coerce("-10000") == Decimal("-10000.00")
    assert money.coerce("123,45") == Decimal("123.45")
    # M1: o separador decimal oficial é a vírgula; ponto permanece cru para
    # ser rejeitado pelo validador de campo.
    assert money.coerce("123.45") == "123.45"
    assert money.coerce("") is None
    assert money.coerce("abc") == "abc"

    integer = FieldDef(2, "QTD", "N", 5, False, 0)
    assert integer.coerce("42") == 42
    assert integer.coerce("-42") == -42
    assert isinstance(integer.coerce("42"), int)


def test_coerce_date_and_text() -> None:
    day = FieldDef(10, "DT_DOC", "N", 8, True, 0)
    assert day.is_date is True
    assert day.coerce("01012024") == date(2024, 1, 1)
    assert day.coerce("31132024") == "31132024"
    assert day.coerce("010124") == "010124"

    text = FieldDef(3, "NOME", "C", 60, False, 0)
    assert text.is_date is False
    assert text.coerce("  ABC  ") == "  ABC  "


def test_register_lookup() -> None:
    fields = (
        FieldDef(1, "REG", "C", 4, True, 0),
        FieldDef(2, "VL_ITEM", "N", 10, False, 2),
    )
    register = RegisterDef("C170", "Item", 3, "1:N", fields)
    assert register.field_names == ("REG", "VL_ITEM")
    assert register.field("VL_ITEM") is fields[1]
    assert register.field(1) is fields[0]
    with pytest.raises(KeyError):
        register.field("NAO_EXISTE")


def test_record_properties() -> None:
    definition = FieldDef(1, "REG", "C", 4, True, 0)
    bad = FieldDef(2, "VL", "N", 3, False, 0)
    record = Record(
        line_no=7,
        code="X001",
        fields=(
            Field(definition, "X001", "X001"),
            Field(bad, "abc", "abc", "erro"),
        ),
        raw="|X001|abc|",
    )
    assert record.errors == ("erro",)
    assert record.values == ("X001", "abc")
    assert record.raw_values == ("X001", "abc")
    assert record.get("REG") == "X001"
    assert record.get("NAO", "padrao") == "padrao"
    assert record.raw_get("VL") == "abc"
    assert record.raw_get("NAO") == ""


def test_empty_numeric_field_is_none() -> None:
    definition = FieldDef(1, "VL", "N", 3, False, 0)
    assert definition.coerce("") is None
