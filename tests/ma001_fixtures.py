"""Synthetic migration evidence. No current players, identities, or calibrated policies."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path

from roster_theory.core.isotonic import MonotoneCurve
from roster_theory.core.models import FantasyTeam, Player, Projection
from roster_theory.core.provenance import AnalysisManifest, DataStamp, stable_hash
from roster_theory.providers.sleeper import SleeperBundle, normalize_league
from roster_theory.trade.boards import BoardPlayerValue, ValueBoard
from roster_theory.trade.schedule import EvaluationWeek
from roster_theory.trade.snapshot import SnapshotCompleteness, TradeSnapshot
from roster_theory.waiver.evaluation import PlayerValueInput
from roster_theory.waiver.policy import load_waiver_policy
from roster_theory.waiver.snapshot import build_waiver_snapshot


ROOT = Path(__file__).parent / 'fixtures' / 'modular'
AS_OF = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
PROFILES = ('reference_a', 'reference_b')


def rules(profile):
    return json.loads((ROOT / 'reference_rules.json').read_text(encoding='utf-8'))['profiles'][profile]


@dataclass(frozen=True)
class ReferenceFixture:
    bundle: SleeperBundle
    projections: tuple[Projection, ...]
    selected: ValueBoard
    market: ValueBoard
    trade: TradeSnapshot
    points: dict[str, float]

    def waiver(self):
        return build_waiver_snapshot(
            league_key=self.trade.league_key, user_id='synthetic-owner-1',
            sleeper=self.bundle, now=AS_OF,
        )

    def values(self):
        return tuple(PlayerValueInput(
            p.player_id, self.points[p.player_id] * 2,
            self.points[p.player_id] * 1.5, self.points[p.player_id] * 3,
            current_week_position_rank=8, rest_of_season_position_rank=8,
            selected_rest_of_season_position_rank=8,
        ) for p in self.bundle.players)


def reference_fixture(profile='reference_a', *, open_slot=False, sparse=False):
    """Full league size/capacity; synthetic three-week estimates, not provider forecasts."""
    config = rules(profile)
    league = normalize_league({
        'league_id': profile, 'season': '2026', 'total_rosters': config['team_count'],
        'roster_positions': config['roster_positions'],
        'scoring_settings': config['scoring_settings'], 'settings': config['settings'],
    })
    starters = tuple(p for p in league.roster_positions if p != 'BN')
    bench = ('QB', 'RB', 'WR', 'TE', 'RB', 'WR')[:league.roster_positions.count('BN')]
    positions = tuple('RB' if 'FLEX' in p else 'DST' if p == 'DEF' else p for p in starters) + bench
    players, teams, points = [], [], {}
    for roster in range(1, league.team_count + 1):
        ids = []
        for index, position in enumerate(positions):
            pid = f'r{roster}_{index}'
            ids.append(pid)
            players.append(Player(pid, f'Synthetic {pid}', (position,), sleeper_id=pid,
                                  nfl_team=('ARI', 'BUF', 'CAR', 'DEN')[index % 4],
                                  active=True, identity_confidence='synthetic'))
            points[pid] = float(20 - index + roster % 3)
        reserve = ()
        if roster == 1 and league.reserve_slots:
            pid = 'r1_reserve'
            players.append(Player(pid, 'Synthetic reserve', ('RB',), sleeper_id=pid,
                                  nfl_team='ARI', active=True, injury_status='Out',
                                  identity_confidence='synthetic'))
            reserve = (pid,)
            points[pid] = 0.0
        if roster == 1 and open_slot:
            ids.pop()
        teams.append(FantasyTeam(str(roster), f'synthetic-owner-{roster}',
                                 f'Synthetic roster {roster}', tuple(ids) + reserve,
                                 tuple(ids[:len(starters)]), reserve, 1, 0))
    for index, position in enumerate(('QB', 'RB', 'WR', 'TE', 'K', 'DST')):
        pid = 'fa_' + position
        players.append(Player(pid, f'Synthetic free {position}', (position,), sleeper_id=pid,
                              nfl_team='SEA', active=True, identity_confidence='synthetic'))
        points[pid] = float(13 + index)
    projections = tuple(Projection(p.player_id, 'WEEKLY', week, (), points[p.player_id],
                                   'synthetic expected points, not a raw-stat scoring proof')
                        for p in players for week in (1, 2, 3)
                        if not sparse or p.player_id != 'r1_0')
    stamp = DataStamp('synthetic', 'fixture://modular', AS_OF, season=2026, week=1, fresh=True)
    bundle = SleeperBundle(AS_OF, (('season', '2026'), ('week', 1)), league,
                           tuple(teams), tuple(players), (), (), None, 0, (stamp,), 'fixture')
    owner = tuple((pid, team.roster_id) for team in teams for pid in team.player_ids)
    owned = dict(owner)
    weeks = tuple(EvaluationWeek(w, False, league.team_count, True, (), True) for w in (1, 2, 3))
    manifest = AnalysisManifest.build(
        league_id=profile, user_id='synthetic-owner-1', current_week=1,
        horizon_start=1, horizon_end=3, configuration={'rules': league, 'fixture': profile},
        normalized_inputs=(players, teams, weeks), data_stamps=(stamp,),
    )
    trade = TradeSnapshot(
        1, 'TRADE ASSISTANT', profile, AS_OF, 'ROS', True, league, '1', tuple(teams),
        tuple(p for p in players if p.positions[0] in ('QB', 'RB', 'WR', 'TE')),
        weeks, tuple(sorted(owner)),
        tuple(p.player_id for p in players if p.player_id not in owned),
        tuple(p.player_id for p in players if p.positions[0] in ('QB', 'RB', 'WR', 'TE')),
        (), (stamp,), (('synthetic', True),), SnapshotCompleteness(True, True, True, True, True, True),
        (), manifest,
    )

    def board(board_id):
        rows = tuple(BoardPlayerValue(p.player_id, p.positions[0], i, i, points[p.player_id] * 3,
                                      i, points[p.player_id] * 3, 0, points[p.player_id] * 2,
                                      points[p.player_id] * 2, 1)
                     for i, p in enumerate(players, 1) if p.positions[0] in ('QB', 'RB', 'WR', 'TE'))
        return ValueBoard(board_id, 'ROS', rows, (), (),
                          MonotoneCurve(((1.0, 1.0),), len(rows), 1), True, (stamp,))
    return ReferenceFixture(bundle, projections, board('selected_final'), board('market'), trade, points)


def policy(profile):
    """Use independent existing synthetic policies; never load a user's policy."""
    name = 'league_alpha' if profile == 'reference_a' else 'league_beta'
    source = Path(__file__).parent / 'fixtures' / 'waiver' / f'{name}.decision-policy.json'
    original = load_waiver_policy(source)
    return replace(original, league_key=profile, version=f'{profile}-synthetic-v1',
                   priority_enabled=False,
                   policy_hash=stable_hash({'profile': profile, 'source': original.policy_hash}))


def draft_fixture(profile):
    config = rules(profile)
    draft = {'draft_id': 'synthetic-draft', 'status': 'drafting',
             'metadata': {'scoring_type': 'half_ppr'},
             'settings': config['draft']['settings']}
    positions = ('QB', 'RB', 'WR', 'TE', 'RB', 'WR', 'K', 'DST')
    board = [{
        'player_key': f'sleeper_id:synthetic-{i}', 'sleeper_id': f'synthetic-{i}',
        'player_name': f'Synthetic player {i}', 'position': positions[(i-1) % len(positions)],
        'team': ('ARI', 'BUF', 'CAR', 'DEN')[i % 4], 'projected_points': float(400-i),
        'adp': i, 'vbd': float(300-i), 'rank_score': i,
    } for i in range(1, 301)]
    return draft, board
