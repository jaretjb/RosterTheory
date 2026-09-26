"""Deterministic, GET-free reproduction from a verified run manifest."""
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from roster_theory.core.provenance import canonical_json
from roster_theory.core.run_contract import load_run_manifest
from roster_theory.providers.cache import atomic_write_json
from roster_theory.waiver.evaluation import load_waiver_evaluation_inputs, evaluate_waiver
from roster_theory.waiver.policy import WaiverDecisionPolicy, apply_waiver_policy, evaluation_options_for_policy
from roster_theory.waiver.priority import WaiverPriorityWeights, build_waiver_priority_scores
from roster_theory.waiver.search import search_waiver_candidates
from roster_theory.waiver.service import _news_freshness
from roster_theory.waiver.snapshot import load_waiver_snapshot


def replay_waiver_manifest(path):
    manifest = load_run_manifest(path)
    replay = manifest['replay']
    with TemporaryDirectory() as directory:
        root = Path(directory)
        atomic_write_json(root/'snapshot.json', replay['snapshot'])
        atomic_write_json(root/'inputs.json', replay['inputs']['bundle'])
        historical = load_waiver_snapshot(root/'snapshot.json')
        inputs = load_waiver_evaluation_inputs(root/'inputs.json')
    # Only the pure historical computation sees current=True at the saved as-of.
    # This function cannot invoke a provider or a publication workflow.
    snapshot = replace(historical, current=True, warnings=tuple(replay['snapshot']['warnings']))
    as_of = datetime.fromisoformat(manifest['as_of'])
    policy = WaiverDecisionPolicy(**replay['policy'])
    request = replay['inputs']['request']
    common = dict(weeks=inputs.weeks, projections=inputs.projections, values=inputs.values,
        drop_legality=dict(inputs.drop_legality), news_fresh=_news_freshness(inputs, as_of),
        contingencies=inputs.contingencies, waiver_wire_evidence=inputs.waiver_wire_evidence,
        emergence_evidence=inputs.emergence_evidence,
        ros_panel_evidence={**(inputs.ros_panel_evidence or {}), 'news_coverage': inputs.news_coverage},
        input_bundle_hash=inputs.input_hash, availability_source=inputs.availability_source, now=as_of)
    if request['operation'] == 'search':
        result = search_waiver_candidates(snapshot, **common, policy=policy,
            enable_pruning=request['enable_pruning'], exact_candidate_budget=request['exact_candidate_budget'])
    elif request['operation'] == 'exact':
        priorities = build_waiver_priority_scores(
            players=snapshot.players, values=inputs.values,
            waiver_wire_evidence=inputs.waiver_wire_evidence,
            owner_by_player=dict(snapshot.owner_by_player), current_bye_teams=inputs.weeks[0].bye_teams,
            weights=WaiverPriorityWeights(weekly=policy.priority_weekly_weight,
                waiver=policy.priority_waiver_weight, ros=policy.priority_ros_weight),
        ) if policy.priority_enabled else {}
        result = apply_waiver_policy(evaluate_waiver(snapshot, **common,
            add=request['add'], drop=request['drop'], waiver_priorities=priorities,
            options=evaluation_options_for_policy(policy)), policy)
    else:
        raise ValueError('Unsupported replay operation')
    if result.evidence_hash != replay['inputs']['result_hash']:
        raise ValueError('Replayed result hash differs from the recorded decision')
    return {'current': False, 'status': 'OFFLINE / NON-ACTIONABLE',
            'result': json.loads(canonical_json(result)), 'manifest_hash': manifest['manifest_hash']}
