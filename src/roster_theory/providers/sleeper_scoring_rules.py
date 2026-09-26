"""Sleeper NFL linear scoring categories and position applicability.

These are calculation rules, not evidence that any provider supplies every
statistic. No omitted field is a documented structural zero here.
"""
from roster_theory.core.scoring_contract import LinearScoringRule


INDIVIDUALS = ("QB", "RB", "WR", "TE", "K")
_RULE_EVIDENCE = "Sleeper scoring categories; docs/MODULAR_PROVIDER_SCORING.md"

# Passing/receiving are possible for all individual offensive positions.
_INDIVIDUAL_SETTINGS = (
    "pass_yd", "pass_td", "pass_int", "pass_2pt", "rush_yd", "rush_td",
    "rush_2pt", "rec", "rec_yd", "rec_td", "rec_2pt", "fum_lost",
    "fum_rec_td", "st_td", "st_ff", "st_fum_rec",
)
_DEFENSE_SETTINGS = (
    "int", "sack", "safe", "blk_kick", "ff", "def_td",
    "def_st_td", "def_st_ff", "def_st_fum_rec", "pts_allow_0",
    "pts_allow_1_6", "pts_allow_7_13", "pts_allow_14_20", "pts_allow_21_27",
    "pts_allow_28_34", "pts_allow_35p",
)
_KICKING_SETTINGS = (
    "fgm", "fgm_0_19", "fgm_20_29", "fgm_30_39", "fgm_40_49",
    "fgm_50_59", "fgm_50p", "fgm_60p", "fgmiss", "fgmiss_0_19",
    "fgmiss_20_29", "fgmiss_30_39", "fgmiss_40_49", "fgmiss_50_59",
    "fgmiss_50p", "fgmiss_60p", "xpm", "xpmiss",
)
SLEEPER_LINEAR_RULES = tuple(
    LinearScoringRule(setting, setting, positions, _RULE_EVIDENCE)
    for settings, positions in (
        (_INDIVIDUAL_SETTINGS, INDIVIDUALS),
        (_DEFENSE_SETTINGS, ("DST",)),
        (_KICKING_SETTINGS, ("K",)),
    ) for setting in settings
) + tuple(
    LinearScoringRule(f"bonus_rec_{position.lower()}", "rec", (position,), _RULE_EVIDENCE)
    for position in ("RB", "WR", "TE")
) + (
    # The position boundary is unresolved; do not guess it for either source.
    LinearScoringRule("fum_rec", "fum_rec", None, "Unresolved applicability; issue #30"),
)
