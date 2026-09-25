from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


STAT_ALIASES: dict[str, tuple[str, ...]] = {
    "pass_yd": ("pass_yd", "pass_yds", "passing_yards"),
    "pass_td": ("pass_td", "pass_tds", "passing_touchdowns"),
    "pass_int": ("pass_int", "pass_ints", "interceptions"),
    "pass_2pt": ("pass_2pt", "passing_2pt"),
    "rush_yd": ("rush_yd", "rush_yds", "rushing_yards"),
    "rush_td": ("rush_td", "rush_tds", "rushing_touchdowns"),
    "rush_2pt": ("rush_2pt", "rushing_2pt"),
    "rec": ("rec", "rec_rec", "receptions"),
    "rec_yd": ("rec_yd", "rec_yds", "receiving_yards"),
    "rec_td": ("rec_td", "rec_tds", "receiving_touchdowns"),
    "rec_2pt": ("rec_2pt", "receiving_2pt"),
    "fum_lost": ("fum_lost", "fumbles_lost", "fumbles"),
    "st_td": ("st_td", "ret_tds"),
    "def_st_ff": ("def_st_ff", "def_ff"),
    "def_st_fum_rec": ("def_st_fum_rec", "def_fr"),
    "int": ("int", "def_int"),
    "sack": ("sack", "def_sack"),
    "safe": ("safe", "def_safety"),
    "def_td": ("def_td",),
    "def_st_td": ("def_st_td", "def_retd"),
    "pts_allow_0": ("pts_allow_0", "def_pa_a"),
    "pts_allow_1_6": ("pts_allow_1_6", "def_pa_b"),
    "pts_allow_7_13": ("pts_allow_7_13", "def_pa_c"),
    "pts_allow_14_20": ("pts_allow_14_20", "def_pa_d"),
    "pts_allow_21_27": ("pts_allow_21_27", "def_pa_e"),
    "pts_allow_28_34": ("pts_allow_28_34", "def_pa_f"),
    "pts_allow_35p": ("pts_allow_35p", "def_pa_g"),
    "fgm": ("fgm",),
    "fgm_0_19": ("fgm_0_19",),
    "fgm_20_29": ("fgm_20_29",),
    "fgm_30_39": ("fgm_30_39",),
    "fgm_40_49": ("fgm_40_49",),
    "fgm_50_59": ("fgm_50_59",),
    "fgm_50p": ("fgm_50p",),
    "fgm_60p": ("fgm_60p",),
    "fgmiss": ("fgmiss",),
    "fgmiss_0_19": ("fgmiss_0_19",),
    "fgmiss_20_29": ("fgmiss_20_29",),
    "fgmiss_30_39": ("fgmiss_30_39",),
    "fgmiss_40_49": ("fgmiss_40_49",),
    "fgmiss_50_59": ("fgmiss_50_59",),
    "fgmiss_50p": ("fgmiss_50p",),
    "fgmiss_60p": ("fgmiss_60p",),
    "xpm": ("xpm",),
    "xpmiss": ("xpmiss",),
}

POSITION_RECEPTION_BONUSES = {"bonus_rec_rb": "RB", "bonus_rec_wr": "WR", "bonus_rec_te": "TE"}


def _number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class ScoringResult:
    points: float
    raw_stats: tuple[tuple[str, Any], ...]
    used_settings: tuple[str, ...]
    unsupported_settings: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unsupported_settings


def score_stats(
    stats: Mapping[str, Any], scoring: Mapping[str, Any], *, position: str | None = None
) -> ScoringResult:
    """Score supplied stats and report every non-zero unsupported setting."""
    total = 0.0
    used: list[str] = []
    supported = set(STAT_ALIASES)
    if position and position.upper() in {"QB", "RB", "WR", "TE", "K", "DST", "DEF"}:
        supported.update(POSITION_RECEPTION_BONUSES)
        receptions = next((_number(stats.get(alias)) for alias in STAT_ALIASES["rec"]
                           if _number(stats.get(alias)) is not None), None)
        for setting, primary in POSITION_RECEPTION_BONUSES.items():
            if position.upper() == primary and receptions is None and (_number(scoring.get(setting)) or 0.0):
                supported.discard(setting)
            if position.upper() == primary and receptions is not None:
                multiplier = _number(scoring.get(setting)) or 0.0
                total += multiplier * receptions
                if multiplier:
                    used.append(setting)
    for setting, aliases in STAT_ALIASES.items():
        multiplier = _number(scoring.get(setting)) or 0.0
        if multiplier == 0.0:
            continue
        value = next(
            (
                parsed
                for alias in aliases
                if (parsed := _number(stats.get(alias))) is not None
            ),
            None,
        )
        if value is not None:
            total += multiplier * value
            used.append(setting)
    unsupported = tuple(
        sorted(
            str(setting)
            for setting, multiplier in scoring.items()
            if str(setting) not in supported and (_number(multiplier) or 0.0) != 0.0
        )
    )
    return ScoringResult(
        points=round(total, 3),
        raw_stats=tuple(sorted((str(key), value) for key, value in stats.items())),
        used_settings=tuple(sorted(used)),
        unsupported_settings=unsupported,
    )
