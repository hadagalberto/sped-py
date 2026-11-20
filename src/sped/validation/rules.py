"""Catálogo de regras do validador PVA-like.

Toda regra tem identificador estável, severidade e mensagem em pt-BR. As
mensagens são modelos :meth:`str.format` preenchidos pelo contexto de
validação; a fonte oficial de cada regra está em ``source``.

Fontes (verificadas em 2026-11-20):

* Guia Prático EFD ICMS/IPI v3.2.4 —
  https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file
* Guia Prático EFD-Contribuições v1.35 —
  http://sped.rfb.gov.br/estatico/AD/06A0F5C4E4CC8CA16035EB891A3AE31EA79708/Guia_Pratico_EFD_Contribuicoes_Versao_1_35%20-%2018_06_2021.pdf
* Manual de Orientação do Leiaute 9 da ECD —
  http://sped.rfb.gov.br/estatico/F3/7FE3D184F7E3F88A9BB2D4EE8218CAF73B21F7/Manual_de_Orienta%C3%A7%C3%A3o_da_ECD_2021_Dezembro_Leiaute_9_(04_01_2022).pdf
* Manual de Orientação do Leiaute 12 da ECF —
  https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

GUIDA_ICMS: Final = (
    "Guia Prático EFD ICMS/IPI v3.2.4, Cap. II seção 5 e Cap. III seção 3 — "
    "https://www.gov.br/sped/pt-br/assuntos/escrituracoes-digitais/efd-icms-ipi/"
    "manuais-e-documentos-tecnicos/guia-pratico-efd-versao-3-2-4.pdf/@@display-file/file"
)
GUIDA_CONTRIB: Final = (
    "Guia Prático EFD-Contribuições v1.35, registros M200/M210/M600/M610 — "
    "http://sped.rfb.gov.br/estatico/AD/06A0F5C4E4CC8CA16035EB891A3AE31EA79708/"
    "Guia_Pratico_EFD_Contribuicoes_Versao_1_35%20-%2018_06_2021.pdf"
)
MANUAL_ECD: Final = (
    "Manual de Orientação do Leiaute 9 da ECD, registro I155 — "
    "http://sped.rfb.gov.br/estatico/F3/7FE3D184F7E3F88A9BB2D4EE8218CAF73B21F7/"
    "Manual_de_Orienta%C3%A7%C3%A3o_da_ECD_2021_Dezembro_Leiaute_9_(04_01_2022).pdf"
)
MANUAL_ECF: Final = (
    "Manual de Orientação do Leiaute 12 da ECF, registros C155/E155/K155 — "
    "https://www.confaz.fazenda.gov.br/legislacao/arquivo-manuais"
)
TABELAS: Final = (
    "Tabelas oficiais agrupadas em src/sped/tables (ver scripts/update_tables.py): "
    "CFOP — Ajuste SINIEF 07/01, "
    "https://www.confaz.fazenda.gov.br/legislacao/ajustes/2001/AJ_007_01; "
    "NCM — Receita Federal/Siscomex, "
    "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json; "
    "CST/CSOSN — Guia Prático EFD ICMS/IPI v3.2.4 e Ajuste SINIEF 03/10, "
    "https://www.confaz.fazenda.gov.br/legislacao/ajustes/2010/AJ_003_10"
)


class Severity(str, Enum):
    """Severidade de uma não conformidade."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Rule:
    """Definição imutável de uma regra de validação."""

    id: str
    title: str
    message: str
    severity: Severity
    source: str

    def format(self, **values: object) -> str:
        """Return the pt-BR message with ``values`` interpolated."""
        return self.message.format(**values)


def _rule(
    rule_id: str, title: str, message: str, source: str, severity: Severity = Severity.ERROR
) -> Rule:
    return Rule(rule_id, title, message, severity, source)


_RULES: Final[tuple[Rule, ...]] = (
    # --- leitura e estrutura -------------------------------------------------
    _rule(
        "SPED-FRAME",
        "Framing/leitura",
        "Falha ao ler o arquivo: {detail}",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-FIELD",
        "Campo do leiaute",
        "Campo inválido: {detail}",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-STRUCT",
        "Estrutura do arquivo",
        "Estrutura inválida: {detail}",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-9900",
        "Registro 9900",
        "9900 {detail}",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-9999",
        "Registro 9999",
        "9999 {detail}",
        GUIDA_ICMS,
    ),
    # --- perfis (EFD ICMS/IPI) -----------------------------------------------
    _rule(
        "SPED-PERFIL-001",
        "Perfil de apresentação",
        "IND_PERFIL {value} inválido no registro 0000; permitidos: A, B e C.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-PERFIL-002",
        "Registro obrigatório por perfil",
        "Registro {register} obrigatório ausente no perfil {perfil}.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-PERFIL-003",
        "Registro dispensado pelo perfil",
        "Registro {register} não deve ser informado no perfil {perfil}.",
        GUIDA_ICMS,
    ),
    # --- tabelas oficiais ----------------------------------------------------
    _rule(
        "SPED-TAB-CFOP-001",
        "CFOP oficial",
        "{register}.CFOP {value} não consta na tabela oficial de CFOP "
        "(Ajuste SINIEF 07/01) ou é código de grupo.",
        TABELAS,
    ),
    _rule(
        "SPED-TAB-CST-001",
        "CST/CSOSN oficial",
        "{register}.CST_ICMS {value} inválido: {detail}",
        TABELAS,
    ),
    _rule(
        "SPED-TAB-NCM-001",
        "NCM oficial",
        "0200.COD_NCM {value} não consta na tabela oficial de NCM vigente.",
        TABELAS,
    ),
    # --- referências cruzadas ------------------------------------------------
    _rule(
        "SPED-XREF-0150-001",
        "Participante não cadastrado",
        "{register} linha {line}: COD_PART {value} não declarado no registro 0150.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-XREF-0200-001",
        "Item não cadastrado",
        "{register} linha {line}: COD_ITEM {value} não declarado no registro 0200.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-XREF-0190-001",
        "Unidade não cadastrada",
        "{register} linha {line}: {field} {value} não declarado no registro {declared_register}.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-XREF-ORDER-001",
        "Cadastro declarado após o uso",
        "Registro {register} usa {field} {value} na linha {line}, mas o cadastro "
        "correspondente só é declarado na linha {declared}.",
        GUIDA_ICMS,
        Severity.WARNING,
    ),
    _rule(
        "SPED-XREF-DUP-001",
        "Cadastro duplicado",
        "Registro {register} declara {field} {value} mais de uma vez.",
        GUIDA_ICMS,
        Severity.WARNING,
    ),
    # --- totalizações: EFD ICMS/IPI -----------------------------------------
    _rule(
        "SPED-TOT-ICMS-C170-001",
        "C170 x C100",
        "C100 linha {line}: soma de VL_ITEM dos C170 ({computed}) divergente de "
        "VL_MERC informado ({stated}).",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-TOT-ICMS-C190-001",
        "C170 x C190",
        "C190 linha {line}: {field} informado {stated} diverge da soma apurada {computed}.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-TOT-ICMS-C190-002",
        "Combinação CST/CFOP/ALIQ duplicada",
        "C190 linha {line}: combinação CST_ICMS/CFOP/ALIQ_ICMS {value} já informada.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-TOT-ICMS-E110-001",
        "C190/D190 x E110",
        "E110.{field} informado {stated} diverge do apurado {computed}.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-TOT-ICMS-E110-002",
        "Saldo devedor apurado",
        "E110.VL_SLD_APURADO informado {stated} diverge do apurado {computed}.",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-TOT-ICMS-E110-003",
        "ICMS a recolher",
        "E110.VL_ICMS_RECOLHER informado {stated} diverge de VL_SLD_APURADO menos "
        "VL_TOT_DED ({computed}).",
        GUIDA_ICMS,
    ),
    _rule(
        "SPED-TOT-ICMS-E110-004",
        "Saldo credor a transportar",
        "E110.VL_SLD_CREDOR_TRANSPORTAR informado {stated} diverge do apurado {computed}.",
        GUIDA_ICMS,
    ),
    # --- totalizações: EFD-Contribuições ------------------------------------
    _rule(
        "SPED-TOT-CONTRIB-M210-001",
        "Base de cálculo ajustada do PIS",
        "M210 linha {line}: VL_BC_CONT_AJUS informado {stated} diverge de {computed}.",
        GUIDA_CONTRIB,
    ),
    _rule(
        "SPED-TOT-CONTRIB-M210-002",
        "Contribuição de PIS do período",
        "M210 linha {line}: VL_CONT_PER informado {stated} diverge de {computed}.",
        GUIDA_CONTRIB,
    ),
    _rule(
        "SPED-TOT-CONTRIB-M610-001",
        "Base de cálculo ajustada da COFINS",
        "M610 linha {line}: VL_BC_CONT_AJUS informado {stated} diverge de {computed}.",
        GUIDA_CONTRIB,
    ),
    _rule(
        "SPED-TOT-CONTRIB-M610-002",
        "Contribuição de COFINS do período",
        "M610 linha {line}: VL_CONT_PER informado {stated} diverge de {computed}.",
        GUIDA_CONTRIB,
    ),
    _rule(
        "SPED-TOT-CONTRIB-M200-001",
        "M210 x M200",
        "M200.{field} informado {stated} diverge da soma dos M210 ({computed}).",
        GUIDA_CONTRIB,
    ),
    _rule(
        "SPED-TOT-CONTRIB-M200-002",
        "M200 totals",
        "M200.{field} informado {stated} diverge do apurado {computed}.",
        GUIDA_CONTRIB,
    ),
    _rule(
        "SPED-TOT-CONTRIB-M600-001",
        "M610 x M600",
        "M600.{field} informado {stated} diverge da soma dos M610 ({computed}).",
        GUIDA_CONTRIB,
    ),
    _rule(
        "SPED-TOT-CONTRIB-M600-002",
        "M600 totals",
        "M600.{field} informado {stated} diverge do apurado {computed}.",
        GUIDA_CONTRIB,
    ),
    # --- totalizações: ECD ---------------------------------------------------
    _rule(
        "SPED-TOT-ECD-001",
        "Balancete débito x crédito",
        "Período {period}: soma de VL_DEB ({computed}) divergente da soma de VL_CRED ({stated}).",
        MANUAL_ECD,
    ),
    _rule(
        "SPED-TOT-ECD-002",
        "Saldo final do balancete",
        "I155 linha {line}: VL_SLD_FIN/IND_DC_FIN informados {stated} divergem do "
        "apurado {computed}.",
        MANUAL_ECD,
    ),
    # --- totalizações: ECF ---------------------------------------------------
    _rule(
        "SPED-TOT-ECF-001",
        "Saldo final dos saldos contábeis",
        "{code} linha {line}: VL_SLD_FIN/IND_VL_SLD_FIN informados {stated} divergem "
        "do apurado {computed}.",
        MANUAL_ECF,
    ),
)

#: Registry of every rule, keyed by its stable id.
RULES: Final[dict[str, Rule]] = {rule.id: rule for rule in _RULES}

if len(RULES) != len(_RULES):
    raise AssertionError("IDs de regra duplicados")
