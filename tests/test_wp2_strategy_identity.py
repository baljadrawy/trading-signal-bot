"""WP2 lane A: strategy-rule identity, config snapshot, decision metadata, boundary report.

Synthetic, in-memory fixtures only (plus files this test writes under tmp_path). No repository
data file, database, network, clock or environment is read. These tests demonstrate engineering
properties (determinism, change detection, fail-closed validation); they say nothing about any
strategy's economics.
"""
import sys; sys.path.insert(0, '.')

import builtins
import copy
import dataclasses
import inspect
import json
import os
import pathlib
import random
import re
import socket
import subprocess
import time

import pytest

from research.foundation.contract import canonical_json as research_canonical_json
from shared import decision_metadata as dm
from shared import strategy_config_snapshot as scs
from shared import strategy_identity as si
from shared import strategy_version_boundary as VBR
from shared.signal_identity import INTEGRITY_MODES
from shared.t1_cap import T1_CAP_POLICIES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── synthetic closure ──────────────────────────────────────────────────────────────────────

ENTRY = (b'CAP = 0.99\n\n\nclass Analyzer:\n    def levels(self, x):\n        return min(x, CAP)\n\n'
         b'    def other(self):\n        return 1\n\n\nQUERY = """SELECT a FROM t ORDER BY a LIMIT 7"""\n')
RULES = b'def rule(x):\n    return x > 1\n'
REGIME = b'def classify(x):\n    return "bullish"\n'
SOURCES = {'pkg/entry.py': ENTRY, 'pkg/rules.py': RULES, 'shared/regime.py': REGIME}
CONTRACT = {k: f'declared-{k}' for k in si.REQUIRED_CONTRACT_KEYS}
H = ['%064x' % i for i in range(1, 9)]


def _files():
    return [si.ClosureFile('pkg/entry.py', 'geometry', (
                si.RegionSpec('entry_levels', 'def:Analyzer.levels'),
                si.RegionSpec('entry_cap', 'assign:CAP'),
                si.RegionSpec('entry_query', 'literal:LIMIT 7'))),
            si.ClosureFile('pkg/rules.py', 'entry'),
            si.ClosureFile('shared/regime.py', 'regime')]


def manifest(sid='synthetic_strategy', files=None):
    return si.StrategyRuleManifest(strategy_id=sid, files=tuple(files or _files()))


SCHEMA = scs.ConfigSchema('synthetic/test-1', (
    scs.ConfigKey('T1_CAP_POLICY', 'enum', 'env', ('legacy_window_v1', 'independent_swing_v1')),
    scs.ConfigKey('WINDOW_N', 'int', 'env'),
    scs.ConfigKey('LEVEL', 'float', 'env'),
    scs.ConfigKey('ENABLED', 'bool', 'env'),
    scs.ConfigKey('TFS', 'str_list', 'env'),
    scs.ConfigKey('LABEL', 'str', 'env'),
    scs.ConfigKey('DB_THRESHOLDS', 'json_object', 'database'),
))
VALUES = {'T1_CAP_POLICY': 'legacy_window_v1', 'WINDOW_N': 3, 'LEVEL': 1.5, 'ENABLED': False,
          'TFS': ['a', 'b'], 'LABEL': 'x', 'DB_THRESHOLDS': {'b': 1, 'a': [1, 2]}}


def snap(sid='synthetic_strategy', **over):
    return scs.snapshot_config(sid, SCHEMA, {**VALUES, **over})


def identity(sources=None, version='1.0.0', sid='synthetic_strategy', lineage=(), contract=None,
             files=None, **cfg):
    return si.build_identity(manifest(sid, files), sources or SOURCES, version=version,
                             config_snapshot=snap(sid, **cfg),
                             contract_descriptor=contract or CONTRACT, lineage=lineage)


def edited(path, old, new):
    data = SOURCES[path]
    assert old in data
    return {**SOURCES, path: data.replace(old, new, 1)}


# ── canonical JSON ─────────────────────────────────────────────────────────────────────────

def test_canonical_json_matches_research_contract_form():
    samples = [{'b': 1, 'a': [1, 2.5, None, True]}, {'x': {'z': 'é', 'y': -0.0}}, [], 'text', 7]
    for value in samples:
        assert si.canonical_json(value) == research_canonical_json(value)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), {1: 'a'}, {'a'}, object(), b'x',
                                 {'k': [float('-inf')]}])
def test_canonical_json_refuses_values_without_a_unique_form(bad):
    with pytest.raises(si.ClosureError):
        si.canonical_json(bad)


# ── source hash ────────────────────────────────────────────────────────────────────────────

def test_source_hash_is_deterministic_and_order_independent():
    base = si.compute_closure(manifest(), SOURCES)
    rng = random.Random(20261101)
    for _ in range(5):
        files = _files()
        rng.shuffle(files)
        files = [dataclasses.replace(f, regions=tuple(rng.sample(f.regions, len(f.regions))))
                 for f in files]
        keys = list(SOURCES)
        rng.shuffle(keys)
        other = si.compute_closure(manifest(files=files), {k: SOURCES[k] for k in keys})
        assert other == base
        assert manifest(files=files) == manifest()
    assert base.source_hash == si.source_hash_from_digests(base.file_map())
    assert base.closure_spec_hash == manifest().closure_spec_hash


def test_newline_normalization_only():
    crlf = {k: v.replace(b'\n', b'\r\n') for k, v in SOURCES.items()}
    assert si.compute_closure(manifest(), crlf) == si.compute_closure(manifest(), SOURCES)
    assert si.file_digest(b'a\n') != si.file_digest(b'a \n')


def test_every_closure_file_edit_changes_source_hash():
    base = si.compute_closure(manifest(), SOURCES).source_hash
    for path in SOURCES:
        for change in (SOURCES[path] + b'# edit\n', SOURCES[path].replace(b'return', b'return ', 1)):
            assert change != SOURCES[path]
            assert si.compute_closure(manifest(), {**SOURCES, path: change}).source_hash != base


def test_missing_or_undeclared_files_are_refused():
    with pytest.raises(si.ClosureError, match='missing'):
        si.compute_closure(manifest(), {k: v for k, v in SOURCES.items() if k != 'pkg/rules.py'})
    with pytest.raises(si.ClosureError, match='not in the declared closure'):
        si.compute_closure(manifest(), {**SOURCES, 'pkg/extra.py': b'x = 1\n'})
    with pytest.raises(si.ClosureError):
        si.compute_closure(manifest(), {**SOURCES, 'pkg/rules.py': 'not bytes'})


def test_reader_reads_only_the_closure(tmp_path):
    for path, data in {**SOURCES, 'pkg/outside.py': b'y = 1\n'}.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    first = si.compute_closure(manifest(), si.read_closure_sources(tmp_path, manifest()))
    (tmp_path / 'pkg/outside.py').write_bytes(b'y = 2\n')
    assert si.compute_closure(manifest(), si.read_closure_sources(tmp_path, manifest())) == first
    (tmp_path / 'pkg/rules.py').write_bytes(RULES + b'\n')
    assert si.compute_closure(manifest(), si.read_closure_sources(tmp_path, manifest())).source_hash \
        != first.source_hash
    (tmp_path / 'pkg/rules.py').unlink()
    with pytest.raises(si.ClosureError, match='not found'):
        si.read_closure_sources(tmp_path, manifest())


def test_region_digests_localize_changes():
    base = {r[0]: r[3] for r in si.compute_closure(manifest(), SOURCES).regions}
    inside = {r[0]: r[3] for r in si.compute_closure(
        manifest(), edited('pkg/entry.py', b'min(x, CAP)', b'max(x, CAP)')).regions}
    assert inside['entry_levels'] != base['entry_levels']
    assert inside['entry_cap'] == base['entry_cap'] and inside['entry_query'] == base['entry_query']
    outside = si.compute_closure(manifest(), edited('pkg/entry.py', b'return 1', b'return 2'))
    assert {r[0]: r[3] for r in outside.regions} == base
    assert outside.source_hash != si.compute_closure(manifest(), SOURCES).source_hash
    query = {r[0]: r[3] for r in si.compute_closure(
        manifest(), edited('pkg/entry.py', b'ORDER BY a', b'ORDER BY b')).regions}
    assert query['entry_query'] != base['entry_query']


@pytest.mark.parametrize('old,new,match', [
    (b'def levels', b'def levels_v2', '0 definitions'),
    (b'    def other(self)', b'    def levels(self)', '2 definitions'),
    (b'CAP = 0.99', b'CAP = 0.99\nCAP = 0.98', '2 module-level'),
    (b'LIMIT 7"""', b'LIMIT 7"""\nQ2 = "LIMIT 7"', '2 string constants'),
    (b'LIMIT 7', b'LIMIT 8', '0 string constants'),
    (b'return min(x, CAP)', b'return min(x, CAP', 'cannot parse'),
])
def test_regions_fail_closed(old, new, match):
    with pytest.raises(si.ClosureError, match=match):
        si.compute_closure(manifest(), edited('pkg/entry.py', old, new))


@pytest.mark.parametrize('make', [
    lambda: si.RegionSpec('ok_id', 'func:x'),
    lambda: si.RegionSpec('ok_id', 'def:'),
    lambda: si.RegionSpec('ok_id', 'assign:A.B'),
    lambda: si.RegionSpec('Bad-Id', 'def:x'),
    lambda: si.ClosureFile('data/x.json', 'r', (si.RegionSpec('a', 'def:x'),)),
    lambda: si.ClosureFile('../x.py', 'r'),
    lambda: si.ClosureFile('/abs/x.py', 'r'),
    lambda: si.ClosureFile('a\\b.py', 'r'),
    lambda: si.ClosureFile('./a.py', 'r'),
    lambda: si.StrategyRuleManifest('s', (si.ClosureFile('a.py', 'r'), si.ClosureFile('a.py', 'r'))),
    lambda: si.StrategyRuleManifest('s', (si.ClosureFile('a.py', 'r', (si.RegionSpec('r', 'def:f'),)),
                                          si.ClosureFile('b.py', 'r', (si.RegionSpec('r', 'def:g'),)))),
    lambda: si.StrategyRuleManifest('Not Valid', (si.ClosureFile('a.py', 'r'),)),
    lambda: si.StrategyRuleManifest('s', ()),
])
def test_manifest_declarations_are_validated(make):
    with pytest.raises(si.ClosureError):
        make()


def test_draft_manifest_covers_the_se04_gap():
    assert set(si.DRAFT_MANIFESTS) == {'momentum_breakout', 'reversion_rsi_bb'}
    for m in si.DRAFT_MANIFESTS.values():
        assert m.status == si.PROPOSAL_STATUS
        legacy = {f.path for f in m.files if f.in_legacy_contract_v1}
        assert legacy == set(si.LEGACY_CONTRACT_V1_SOURCES)
        outside = set(m.outside_legacy_contract_v1())
        assert {'analyzer/technical_analyzer.py', 'shared/t1_cap.py', 'shared/signal_identity.py',
                'signal_engine/main.py', 'trade_tracker/main.py', 'shared/fees.py'} <= outside
        selectors = {(f.path, r.selector) for f in m.files for r in f.regions}
        assert ('analyzer/technical_analyzer.py', 'def:TechnicalAnalyzer._calculate_levels') in selectors
        assert ('signal_engine/main.py', 'literal:LIMIT 200') in selectors
        assert ('signal_engine/main.py', 'assign:SELECTION_LIMIT') in selectors
        assert ('shared/t1_cap.py', 'def:capped_t1') in selectors
        assert ('shared/signal_identity.py', 'def:SetupIdentity') in selectors
        assert ('trade_tracker/main.py', 'def:close_trade_barrier') in selectors


def test_draft_manifest_classification_follows_the_call_path_inventory():
    a, b = (si.DRAFT_MANIFESTS[k] for k in si.CURRENT_FAMILY_IDS)
    assert a.files == b.files                     # one shared pipeline, identity split only (SE-39)
    active = set(a.active_paths)
    # added by the WP-A01 call-path trace (STRATEGY_INTERFACE_v1.md section 3)
    assert {'analyzer/main.py', 'analyzer/orderbook_analyzer.py', 'scanner/main.py', 'shared/ohlcv.py',
            'shared/candle.py', 'shared/maintenance.py', 'shared/trading_state.py',
            'shared/signal_readiness.py', 'shared/entry_execution.py', 'shared/execution.py',
            'shared/economic_halt_policy.py', 'shared/risk_epoch.py', 'telegram/main.py',
            'telegram/whitelist.py', 'trade_tracker/binance_price_stream.py',
            'shared/macro_context.py'} <= active
    cls = {f.path: f.classification for f in a.files}
    assert cls['shared/strategy_math.py'] == si.POTENTIAL
    assert a.legacy_contract_v1_inactive() == ('shared/strategy_math.py',)
    for path in ('shared/learning_governance.py', 'shared/dependency_safety.py',
                 'research/continuous_learner.py'):
        assert cls[path] == si.DORMANT
    regions = {r.selector: r.classification for f in a.files for r in f.regions}
    assert regions['def:SignalEngine.find_best_signal'] == si.DORMANT
    assert regions['def:SignalEngine.find_best_signal_live'] == si.ACTIVE
    assert regions['def:independent_swing_resistance'] == si.DORMANT
    assert regions['def:SetupIdentity'] == si.DORMANT and regions['def:integrity_mode'] == si.ACTIVE
    assert regions['def:MacroContext.should_block_now'] == si.ACTIVE
    regions_scoped = {'telegram/main.py', 'shared/admission_capacity.py'}
    assert {f.path for f in a.files if f.scope == si.REGIONS_SCOPE} == regions_scoped
    # WP2 integrations (cf04a4a, 9bc6f2e): decision and booking paths are ACTIVE ...
    assert {'shared/selection_policy.py', 'shared/capacity_authority.py', 'shared/admission_capacity.py',
            'shared/accounting_flags.py', 'shared/cost_label_policy.py', 'shared/cost_models.py'} <= active
    # ... telemetry and shadows are OBSERVE_ONLY and never feed source_hash
    observe = {p for p, c in cls.items() if c == si.OBSERVE_ONLY}
    assert observe == {'shared/funnel_flags.py', 'shared/funnel_hooks.py', 'shared/funnel_records.py',
                       'shared/funnel_recorder.py', 'shared/ledger_legacy_adapter.py',
                       'shared/portfolio_ledger.py', 'shared/position_state_shadow.py',
                       'shared/position_state.py'}
    assert regions['def:rank_then_limit'] == si.DORMANT
    assert regions['def:selection_policy_from_env'] == si.ACTIVE
    assert regions['def:routed_risk_decision'] == si.ACTIVE
    assert regions['def:TrackerAdmissionFunnel'] == si.OBSERVE_ONLY
    assert regions['def:single_count_close'] == si.DORMANT


def test_draft_closure_resolves_on_this_tree():
    """Reads only the declared closure source files of this checkout (no data)."""
    for sid, m in si.DRAFT_MANIFESTS.items():
        digest = si.compute_closure(m, si.read_closure_sources(pathlib.Path(ROOT), m))
        assert len(digest.regions) >= 22 and len(digest.files) == len(m.active_paths)
        assert {p for p, _c, _d in digest.inactive_files} == set(m.inactive_paths)
        assert digest.inactive_hash is not None


# ── classification and scope ───────────────────────────────────────────────────────────────

def test_hash_scheme_unchanged_for_all_active_file_scoped_manifests():
    """Values computed with the iteration-1 module (9668485): the new fields are backward compatible."""
    d = si.compute_closure(manifest(), SOURCES)
    assert d.source_hash == '5d6191bffcebaad3d7a1eeb8e1856104396da6c0144069cd9ade9d4c58fba156'
    assert d.closure_spec_hash == '56e1c4ebda77e3b1448739c915e7ff569b5c88af258d7ca93fc4c5f3b34fc617'
    assert d.inactive_files == () and d.inactive_hash is None
    spec = manifest().spec()
    assert all(set(f) == {'path', 'regions'} and all(len(r) == 2 for r in f['regions'])
               for f in spec['files'])


def _with(path, **over):
    return [dataclasses.replace(f, **over) if f.path == path else f for f in _files()]


def test_inactive_files_are_hashed_separately():
    m = manifest(files=_with('pkg/rules.py', classification=si.DORMANT))
    base, edit = (si.compute_closure(m, src) for src in
                  (SOURCES, edited('pkg/rules.py', b'x > 1', b'x > 2')))
    assert 'pkg/rules.py' not in base.file_map()
    assert base.source_hash == edit.source_hash and base.inactive_hash != edit.inactive_hash
    assert base.inactive_files[0][:2] == ('pkg/rules.py', si.DORMANT)
    assert m.closure_spec_hash != manifest().closure_spec_hash
    assert base.source_hash != si.compute_closure(manifest(), SOURCES).source_hash
    with pytest.raises(si.ClosureError, match='missing'):
        si.compute_closure(m, {k: v for k, v in SOURCES.items() if k != 'pkg/rules.py'})


def test_regions_scope_counts_active_regions_only():
    regions = (si.RegionSpec('entry_levels', 'def:Analyzer.levels'),
               si.RegionSpec('entry_cap', 'assign:CAP', classification=si.DORMANT),
               si.RegionSpec('entry_query', 'literal:LIMIT 7'))
    m = manifest(files=_with('pkg/entry.py', regions=regions, scope=si.REGIONS_SCOPE))
    base = si.compute_closure(m, SOURCES)
    for old, new, moves in ((b'return 1', b'return 2', False), (b'CAP = 0.99', b'CAP = 0.98', False),
                            (b'min(x, CAP)', b'max(x, CAP)', True), (b'ORDER BY a', b'ORDER BY b', True)):
        other = si.compute_closure(m, edited('pkg/entry.py', old, new))
        assert (other.source_hash != base.source_hash) is moves, old
    assert len(base.regions) == 3


@pytest.mark.parametrize('make', [
    lambda: si.ClosureFile('a.py', 'r', classification='LIVE'),
    lambda: si.ClosureFile('a.py', 'r', scope='lines'),
    lambda: si.ClosureFile('a.py', 'r', (si.RegionSpec('x', 'def:f', classification=si.DORMANT),),
                           scope=si.REGIONS_SCOPE),
    lambda: si.RegionSpec('x', 'def:f', classification='OFF'),
    lambda: si.StrategyRuleManifest('s', (si.ClosureFile('a.py', 'r', classification=si.POTENTIAL),)),
])
def test_classification_and_scope_are_validated(make):
    with pytest.raises(si.ClosureError):
        make()


def test_closure_document_and_cross_schema_comparison():
    m = manifest(files=_with('pkg/rules.py', classification=si.POTENTIAL))
    doc = si.closure_document(m, SOURCES)
    assert doc['schema'] == si.CLOSURE_DOCUMENT_SCHEMA and 'config_hash' not in doc
    assert doc['inactive_files']['pkg/rules.py']['classification'] == si.POTENTIAL
    sv_, ident = si.build_identity(m, SOURCES, version='1.0.0', config_snapshot=snap(),
                                   contract_descriptor=CONTRACT)
    assert ident['source_hash'] == doc['source_hash'] == sv_.source_hash
    report = si.compare_to_reference(doc, ident)
    assert report['reference_kind'] == 'identity_manifest' and report['source_hash_equal'] is True
    assert report['config_hash_equal'] is None and report['inactive_hash_equal'] is True
    later = si.closure_document(m, edited('pkg/rules.py', b'x > 1', b'x > 2'))
    report = si.compare_to_reference(later, doc)
    assert report['reference_kind'] == 'closure_document'
    assert report['source_hash_equal'] is True and report['inactive_files_changed'] == ['pkg/rules.py']


# ── StrategyVersion ────────────────────────────────────────────────────────────────────────

def sv(**over):
    base = dict(strategy_id='synthetic_strategy', version='1.0.0', source_hash=H[0],
                config_hash=H[1], contract_hash=H[2])
    return si.StrategyVersion(**{**base, **over})


def test_lineage_is_metadata_not_identity():
    a, b = sv(), sv(lineage=('legacy_research_contract', 'x' * 8))
    assert a == b and a.identity_hash == b.identity_hash and a.identifier == b.identifier
    assert 'lineage' not in a.identity()


@pytest.mark.parametrize('field,value', [('strategy_id', 'other_strategy'), ('version', '1.0.1'),
                                         ('source_hash', H[3]), ('config_hash', H[3]),
                                         ('contract_hash', H[3])])
def test_each_identity_field_changes_the_identity(field, value):
    assert sv(**{field: value}).identity_hash != sv().identity_hash


@pytest.mark.parametrize('over', [{'version': '1.0'}, {'version': '01.0.0'}, {'version': 'v1.0.0'},
                                  {'source_hash': 'ABC'}, {'config_hash': 'A' * 64},
                                  {'contract_hash': None}, {'strategy_id': ''},
                                  {'lineage': ('',)}])
def test_strategy_version_is_validated(over):
    with pytest.raises(si.ClosureError):
        sv(**over)


def test_frozen_types_refuse_mutation():
    with pytest.raises(dataclasses.FrozenInstanceError):
        sv().version = '2.0.0'
    with pytest.raises(dataclasses.FrozenInstanceError):
        manifest().files = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap().config_hash = H[0]
    with pytest.raises(TypeError):
        si.HISTORICAL_FREEZE['recomputed'] = True


def test_contract_descriptor_hash():
    reordered = dict(reversed(list(CONTRACT.items())))
    assert si.contract_descriptor_hash(reordered) == si.contract_descriptor_hash(CONTRACT)
    assert si.contract_descriptor_hash({**CONTRACT, 'holding_policy': 'other'}) \
        != si.contract_descriptor_hash(CONTRACT)
    with pytest.raises(si.ClosureError, match='missing keys'):
        si.contract_descriptor_hash({k: v for k, v in CONTRACT.items() if k != 'fill_model_id'})


def test_build_identity_is_deterministic():
    (a, doc_a), (b, doc_b) = identity(), identity()
    assert a == b and si.canonical_json(doc_a) == si.canonical_json(doc_b)
    assert doc_a['schema'] == si.IDENTITY_MANIFEST_SCHEMA
    assert doc_a['identity_hash'] == a.identity_hash
    assert doc_a['files']['shared/regime.py']['in_legacy_contract_v1'] is True
    assert doc_a['files']['pkg/entry.py']['in_legacy_contract_v1'] is False
    assert doc_a['historical_freeze']['status'] == 'SEPARATE_UNCHANGED_ARTIFACT'
    with pytest.raises(si.ClosureError, match='another strategy_id'):
        si.build_identity(manifest(), SOURCES, version='1.0.0', config_snapshot=snap('other_one'),
                          contract_descriptor=CONTRACT)


def test_compare_to_reference_reports_files_regions_and_freeze_flag():
    _, ref = identity()
    _, cur = identity(edited('pkg/entry.py', b'min(x, CAP)', b'max(x, CAP)'))
    report = si.compare_to_reference(cur, ref)
    assert report['files_changed'] == ['pkg/entry.py'] and report['files_unchanged'] == 2
    assert report['changed_outside_legacy_contract_v1'] == ['pkg/entry.py']
    assert report['regions_changed'] == ['entry_levels']
    assert report['source_hash_equal'] is False and report['config_hash_equal'] is True
    freeze = report['historical_freeze']
    assert freeze['read'] is False and freeze['recomputed'] is False
    assert freeze['comparable_with_source_hash'] is False
    plain = {p: v['sha256'] for p, v in ref['files'].items() if p != 'pkg/rules.py'}
    plain['pkg/gone.py'] = H[4]
    report = si.compare_to_reference(cur, plain)
    assert report['reference_kind'] == 'file_digests'
    assert report['files_added'] == ['pkg/rules.py'] and report['files_removed'] == ['pkg/gone.py']
    assert si.compare_to_reference(ref, ref)['source_hash_equal'] is True
    with pytest.raises(si.ClosureError):
        si.compare_to_reference(cur, {'pkg/entry.py': 'not-a-digest'})


# ── config snapshot ────────────────────────────────────────────────────────────────────────

def test_config_snapshot_is_deterministic_and_order_independent():
    reordered = dict(reversed(list(VALUES.items())))
    reordered['DB_THRESHOLDS'] = {'a': [1, 2], 'b': 1}
    assert scs.snapshot_config('synthetic_strategy', SCHEMA, reordered) == snap()
    assert snap(LEVEL=2) == snap(LEVEL=2.0)
    keys = list(SCHEMA.keys)
    random.Random(7).shuffle(keys)
    assert scs.ConfigSchema('synthetic/test-1', tuple(keys)).schema_hash == SCHEMA.schema_hash


@pytest.mark.parametrize('key,value', [('T1_CAP_POLICY', 'independent_swing_v1'), ('WINDOW_N', 4),
                                       ('LEVEL', 1.25), ('ENABLED', True), ('TFS', ['b', 'a']),
                                       ('LABEL', 'y'), ('DB_THRESHOLDS', {'b': 2, 'a': [1, 2]})])
def test_every_decision_key_changes_config_hash(key, value):
    other = snap(**{key: value})
    assert other.config_hash != snap().config_hash
    assert scs.changed_keys(snap(), other) == [key]


def test_schema_change_changes_config_hash():
    keys = tuple(scs.ConfigKey('LABEL', 'enum', 'env', ('x', 'y')) if k.name == 'LABEL' else k
                 for k in SCHEMA.keys)
    other = scs.snapshot_config('synthetic_strategy', scs.ConfigSchema('synthetic/test-1', keys), VALUES)
    assert other.values() == snap().values() and other.config_hash != snap().config_hash


@pytest.mark.parametrize('values,match', [
    ({k: v for k, v in VALUES.items() if k != 'LEVEL'}, 'missing'),
    ({**VALUES, 'UNDECLARED': 1}, 'undeclared'),
    ({**VALUES, 'WINDOW_N': True}, 'bool'),
    ({**VALUES, 'WINDOW_N': 3.0}, 'expected int'),
    ({**VALUES, 'LEVEL': float('nan')}, 'finite'),
    ({**VALUES, 'LEVEL': 10 ** 400}, 'finite'),
    ({**VALUES, 'LEVEL': '1.5'}, 'finite'),
    ({**VALUES, 'ENABLED': 0}, 'expected bool'),
    ({**VALUES, 'T1_CAP_POLICY': 'LEGACY_WINDOW_V1'}, 'not in'),
    ({**VALUES, 'TFS': ['a', 1]}, 'list of str'),
    ({**VALUES, 'LABEL': None}, 'expected str'),
    ({**VALUES, 'DB_THRESHOLDS': {'a': float('inf')}}, 'non-finite'),
    ({}, 'missing'),
])
def test_config_snapshot_fails_closed(values, match):
    with pytest.raises(scs.ConfigSnapshotError, match=match):
        scs.snapshot_config('synthetic_strategy', SCHEMA, values)


def test_config_snapshot_roundtrip_and_tamper_detection():
    s = snap()
    assert scs.StrategyConfigSnapshot.from_dict(json.loads(json.dumps(s.to_dict()))) == s
    doc = s.to_dict()
    doc['values']['LEVEL'] = 9.0
    with pytest.raises(scs.ConfigSnapshotError, match='does not match'):
        scs.StrategyConfigSnapshot.from_dict(doc)
    with pytest.raises(scs.ConfigSnapshotError, match='canonical'):
        dataclasses.replace(s, values_json=s.values_json.replace(',', ', ', 1))
    values = s.values()
    values['LEVEL'] = 0.0
    assert s.values()['LEVEL'] == 1.5


def test_draft_schema_declares_names_only():
    names = {k.name: k for k in scs.DRAFT_CURRENT_FAMILY_SCHEMA.keys}
    assert names['T1_CAP_POLICY'].choices == tuple(T1_CAP_POLICIES)
    assert names['SIGNAL_INTEGRITY_MODE'].choices == tuple(INTEGRITY_MODES)
    assert names['DB_INDICATOR_WEIGHTS'].source == names['DB_SYMBOL_BLACKLIST'].source == 'database'
    assert {'LIVE_LEARNING_MODE', 'USDTD_SPIKE_PP', 'MACRO_MAX_STALE_HOURS', 'PAPER_ENTRY_FILL_MODEL'} <= set(names)
    assert 'APP_VERSION' not in names          # enters only the enforce-mode key (DORMANT path)
    assert {'SELECTION_POLICY', 'PAPER_COST_LABEL_POLICY', 'PAPER_BREAK_EVEN_POLICY'} <= set(names)
    assert names['SELECTION_VERSION'].read_when == ('SELECTION_POLICY', ('rank_then_limit_v1',))
    assert not {'FUNNEL_RECORDING', 'LEDGER_SHADOW', 'POSITION_STATE_SHADOW'} & set(names)
    assert not any(hasattr(k, 'default') for k in names.values())
    with pytest.raises(scs.ConfigSnapshotError, match='missing'):
        scs.snapshot_config('momentum_breakout', scs.DRAFT_CURRENT_FAMILY_SCHEMA, {})


CSCHEMA = scs.ConfigSchema('synthetic/conditional-1', (
    scs.ConfigKey('POLICY', 'enum', 'env', ('legacy', 'ranked')),
    scs.ConfigKey('VERSION', 'str', 'env', read_when=('POLICY', ('ranked',))),
))


def test_conditional_keys_enter_config_hash_only_when_read():
    legacy = scs.snapshot_config('synthetic_strategy', CSCHEMA, {'POLICY': 'legacy', 'VERSION': None})
    assert legacy.values() == {'POLICY': 'legacy', 'VERSION': None}
    v1, v2 = (scs.snapshot_config('synthetic_strategy', CSCHEMA, {'POLICY': 'ranked', 'VERSION': v})
              for v in ('sel-v1', 'sel-v2'))
    assert len({legacy.config_hash, v1.config_hash, v2.config_hash}) == 3   # R5.d: version in hash
    with pytest.raises(scs.ConfigSnapshotError, match='supply its effective value'):
        scs.snapshot_config('synthetic_strategy', CSCHEMA, {'POLICY': 'ranked', 'VERSION': None})
    with pytest.raises(scs.ConfigSnapshotError, match='supply None'):
        scs.snapshot_config('synthetic_strategy', CSCHEMA, {'POLICY': 'legacy', 'VERSION': 'sel-v1'})
    with pytest.raises(scs.ConfigSnapshotError, match='missing'):
        scs.snapshot_config('synthetic_strategy', CSCHEMA, {'POLICY': 'legacy'})


@pytest.mark.parametrize('make', [
    lambda: scs.ConfigKey('A', 'str', 'env', read_when=('A', ('x',))),
    lambda: scs.ConfigKey('A', 'str', 'env', read_when=('B',)),
    lambda: scs.ConfigKey('A', 'str', 'env', read_when=('B', ())),
    lambda: scs.ConfigSchema('s/1', (scs.ConfigKey('A', 'str', 'env', read_when=('B', ('x',))),)),
])
def test_conditional_key_declarations_are_validated(make):
    with pytest.raises(scs.ConfigSnapshotError):
        make()


# ── decision metadata ──────────────────────────────────────────────────────────────────────

RUNTIME = {'boot_id': 'boot-a', 'code_sha': 'c' * 40, 'compose_config_hash': H[5],
           'image_id': 'sha256:' + H[6], 'runtime_manifest_hash': None}
T0 = 1_760_000_000_000


def decision(**over):
    base = dict(decision_type='candidate', strategy=sv(),
                input_hashes={'candle_set_hash': H[3], 'regime_context_hash': H[4]},
                input_facts={'regime_point_in_time': False, 'market_source': 'synthetic'},
                bar_close_time_ms=T0, decision_time_ms=T0 + 5_000, output={'symbol': 'AAAUSDT'},
                runtime=RUNTIME, cost_model_id='cost_model_a', fill_model_id='fill_model_a',
                selection_version='sel_v1')
    return dm.make_decision(**{**base, **over})


def test_decision_id_is_deterministic_and_order_independent():
    a = decision()
    b = decision(input_hashes={'regime_context_hash': H[4], 'candle_set_hash': H[3]},
                 input_facts={'market_source': 'synthetic', 'regime_point_in_time': False},
                 runtime=dict(reversed(list(RUNTIME.items()))))
    assert a == b and a.to_json() == b.to_json()
    assert re.fullmatch(r'[0-9a-f]{64}', a.decision_id) and a.decision_id != a.record_hash


@pytest.mark.parametrize('over', [{'decision_time_ms': T0 + 9_000}, {'recorded_at_ms': T0 + 9_500},
                                  {'runtime': {**RUNTIME, 'boot_id': 'boot-b'}},
                                  {'output': {'symbol': 'BBBUSDT'}}, {'prev_record_hash': H[7]}])
def test_wall_clock_runtime_and_output_stay_out_of_decision_id(over):
    a, b = decision(), decision(**over)
    assert a.decision_id == b.decision_id and a.record_hash != b.record_hash


@pytest.mark.parametrize('over', [{'strategy': sv(source_hash=H[7])}, {'strategy': sv(version='2.0.0')},
                                  {'decision_type': 'rejection'}, {'bar_close_time_ms': T0 + 1},
                                  {'input_hashes': {'candle_set_hash': H[7], 'regime_context_hash': H[4]}},
                                  {'input_facts': {'regime_point_in_time': True, 'market_source': 'synthetic'}},
                                  {'cost_model_id': 'cost_model_b'}, {'fill_model_id': None},
                                  {'selection_version': 'sel_v2'}, {'parent_decision_ids': [H[0]]}])
def test_decision_id_changes_with_identity_and_inputs(over):
    assert decision(**over).decision_id != decision().decision_id


def test_lineage_never_enters_a_record():
    assert decision(strategy=sv(lineage=('parent_a',))).to_json() == decision().to_json()
    assert 'lineage' not in decision().to_json()


def test_record_without_complete_identity_is_refused():
    rec = decision()
    for field in ('strategy_version', 'source_hash', 'config_hash', 'contract_hash'):
        with pytest.raises(dm.DecisionMetadataError, match='incomplete strategy identity'):
            dataclasses.replace(rec, **{field: ''})
    with pytest.raises(dm.DecisionMetadataError):
        decision(strategy=sv().identity())


def test_roundtrip_and_tamper_detection():
    rec = decision(parent_decision_ids=[H[2], H[1]], recorded_at_ms=T0 + 6_000)
    assert rec.parent_decision_ids == (H[1], H[2])
    assert dm.DecisionMetadata.from_dict(json.loads(rec.to_json())) == rec
    for path, value in ((('output', 'symbol'), 'ZZZUSDT'), (('decision_id',), H[0]),
                        (('strategy', 'config_hash'), H[7]), (('times', 'decision_time_ms'), T0 + 1),
                        (('runtime', 'boot_id'), 'boot-x')):
        doc = json.loads(rec.to_json())
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with pytest.raises(dm.DecisionMetadataError):
            dm.DecisionMetadata.from_dict(doc)
    doc = json.loads(rec.to_json())
    doc['schema'] = 'other/1'
    with pytest.raises(dm.DecisionMetadataError, match='schema'):
        dm.DecisionMetadata.from_dict(doc)
    with pytest.raises(dm.DecisionMetadataError, match='malformed'):
        dm.DecisionMetadata.from_dict({'schema': dm.SCHEMA})


@pytest.mark.parametrize('over', [
    {'decision_type': 'trade'}, {'input_hashes': {'Bad-Name': H[0]}},
    {'input_hashes': {'candle_set_hash': 'abc'}}, {'input_facts': {'f': [1]}},
    {'input_facts': {'f': float('nan')}}, {'runtime': {'code_sha': 'x'}},
    {'runtime': {**RUNTIME, 'image_id': ''}}, {'decision_time_ms': 0}, {'decision_time_ms': True},
    {'bar_close_time_ms': -1}, {'output': {'p': float('inf')}}, {'output': ['not', 'a', 'mapping']},
    {'parent_decision_ids': [H[0], H[0]]}, {'parent_decision_ids': H[0]},
    {'prev_record_hash': 'abc'}, {'cost_model_id': 'bad id with spaces'},
])
def test_decision_metadata_is_validated(over):
    with pytest.raises(dm.DecisionMetadataError):
        decision(**over)


# ── version-boundary report ────────────────────────────────────────────────────────────────

def test_report_no_change_and_lineage_only():
    _, a = identity()
    _, b = identity(lineage=('legacy_research_contract',))
    report = VBR.version_boundary_report(a, b)
    assert report['classification'] == 'NO_CHANGE' and report['drift_status'] == 'MATCH'
    assert report['lineage_changed'] is True and report['boundary_entry_draft'] is None
    assert report['boundary_required'] == 'NO'


def test_report_label_only():
    _, a = identity()
    _, b = identity(version='1.0.1')
    report = VBR.version_boundary_report(a, b)
    assert report['classification'] == 'LABEL_ONLY' and report['boundary_required'] == 'NO'
    assert any('without any rule' in f for f in report['flags'])
    # SK-09: a label-only change still moves the identity tuple, so decision keys re-key
    assert report['activation_record_required'] is True
    entry = report['boundary_entry_draft']
    assert entry['entry_kind'] == 'identity_rekey' and entry['activation_utc_minute'] == 'PENDING'
    assert 'never re-evaluated' in entry['no_refire_rule']


def test_activation_record_follows_the_identity_tuple_only():
    _, a = identity()
    lineage_only = VBR.version_boundary_report(a, identity(lineage=('parent',))[1])
    assert lineage_only['activation_record_required'] is False
    assert lineage_only['boundary_entry_draft'] is None
    declared = VBR.version_boundary_report(a, identity(edited('pkg/rules.py', b'x > 1', b'x > 2'),
                                                       version='2.0.0')[1])
    assert declared['activation_record_required'] is True
    assert declared['boundary_entry_draft']['entry_kind'] == 'strategy_boundary'
    other = VBR.version_boundary_report(a, identity(sid='another_strategy')[1])
    assert other['activation_record_required'] is False


def test_report_undeclared_change_is_a_stop_condition():
    _, a = identity()
    _, b = identity(edited('pkg/entry.py', b'CAP = 0.99', b'CAP = 0.95'))
    report = VBR.version_boundary_report(a, b)
    assert report['classification'] == 'UNDECLARED_CHANGE'
    assert report['boundary_required'] == 'STOP' and report['drift_status'] == 'SAFETY'
    assert report['hash_changed'] == {'source_hash': True, 'config_hash': False, 'contract_hash': False}
    assert report['regions_changed'] == ['entry_cap']
    assert report['boundary_entry_draft']['activation_utc_minute'] == 'PENDING'


def test_report_declared_major_and_minor_steps():
    _, a = identity()
    _, major = identity(edited('pkg/rules.py', b'x > 1', b'x > 2'), version='2.0.0')
    report = VBR.version_boundary_report(a, major)
    assert report['classification'] == 'DECLARED_CHANGE' and report['version_step'] == 'MAJOR'
    assert report['boundary_required'] == 'YES'
    entry = report['boundary_entry_draft']
    assert entry['source_hash_before'] == a['source_hash'] and entry['source_hash_after'] == major['source_hash']
    assert entry['cost_model_id'] == CONTRACT['cost_model_id'] and entry['boundary_id'] == 'PENDING'
    assert entry['write_status'].startswith('NOT_WRITTEN')
    _, minor = identity(version='1.1.0', LEVEL=2.5)
    report = VBR.version_boundary_report(a, minor)
    assert report['boundary_required'] == 'CONDITIONAL_ON_GOLDEN_REPLAY'
    assert report['config_keys_changed'] == ['LEVEL'] and report['files_changed'] == []
    assert any('golden replay' in f for f in report['flags'])
    _, down = identity(version='0.9.0', LEVEL=2.5)
    assert any('decreased' in f for f in VBR.version_boundary_report(a, down)['flags'])


def test_report_closure_change_and_different_strategy():
    _, a = identity()
    files = _files() + [si.ClosureFile('pkg/new.py', 'exit')]
    _, b = identity({**SOURCES, 'pkg/new.py': b'z = 1\n'}, version='2.0.0', files=files)
    report = VBR.version_boundary_report(a, b)
    assert report['files_added'] == ['pkg/new.py']
    assert any('declared closure changed' in f for f in report['flags'])
    _, other = identity(sid='another_strategy')
    report = VBR.version_boundary_report(a, other)
    assert report['classification'] == 'DIFFERENT_STRATEGY'
    assert report['boundary_required'] == 'NOT_APPLICABLE'


def test_report_is_deterministic_and_does_not_mutate_inputs():
    _, a = identity()
    _, b = identity(edited('pkg/rules.py', b'x > 1', b'x > 2'), version='2.0.0')
    a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
    first = si.canonical_json(VBR.version_boundary_report(a, b))
    assert si.canonical_json(VBR.version_boundary_report(a, b)) == first
    assert a == a0 and b == b0
    report = VBR.version_boundary_report(a, b)
    report['historical_freeze']['recomputed'] = True
    assert si.HISTORICAL_FREEZE['recomputed'] is False


@pytest.mark.parametrize('mutate', [lambda d: d.update(schema='x/1'), lambda d: d.update(version='1'),
                                    lambda d: d.update(source_hash='zz'), lambda d: d.pop('identity_hash')])
def test_report_refuses_invalid_manifests(mutate):
    _, a = identity()
    bad = copy.deepcopy(a)
    mutate(bad)
    with pytest.raises(VBR.ReportError):
        VBR.version_boundary_report(a, bad)


def test_cli_exit_codes(tmp_path, capsys):
    _, a = identity()
    _, same_label = identity(edited('pkg/rules.py', b'x > 1', b'x > 2'))
    _, declared = identity(edited('pkg/rules.py', b'x > 1', b'x > 2'), version='2.0.0')
    paths = {}
    for name, doc in (('a', a), ('u', same_label), ('d', declared)):
        paths[name] = tmp_path / f'{name}.json'
        paths[name].write_text(json.dumps(doc))
    (tmp_path / 'bad.json').write_text('{')
    assert VBR.main([str(paths['a']), str(paths['a'])]) == 0
    assert VBR.main([str(paths['a']), str(paths['d'])]) == 1
    assert VBR.main([str(paths['a']), str(paths['u'])]) == 3
    assert VBR.main([str(paths['a']), str(tmp_path / 'bad.json')]) == 2
    assert VBR.main([str(paths['a'])]) == 2
    out = capsys.readouterr().out.strip().splitlines()
    assert json.loads(out[0])['classification'] == 'NO_CHANGE'


# ── purity, dormancy, freeze artefact ──────────────────────────────────────────────────────

def test_pure_functions_touch_no_file_clock_environment_or_network(monkeypatch):
    _, ref = identity()
    rec = decision()

    def refuse(*_a, **_k):
        raise AssertionError('forbidden side effect')

    class RefusingEnviron(dict):
        def __getitem__(self, key):
            refuse()
        get = __contains__ = keys = items = __iter__ = __getitem__

    for target, name in ((builtins, 'open'), (socket, 'socket'), (socket, 'create_connection'),
                         (time, 'time'), (time, 'time_ns'), (time, 'monotonic'), (os, 'getenv'),
                         (pathlib.Path, 'read_bytes'), (pathlib.Path, 'read_text'),
                         (pathlib.Path, 'write_bytes'), (pathlib.Path, 'write_text'),
                         (pathlib.Path, 'open')):
        monkeypatch.setattr(target, name, refuse)
    monkeypatch.setattr(os, 'environ', RefusingEnviron())
    _, cur = identity(edited('pkg/entry.py', b'CAP = 0.99', b'CAP = 0.9'), version='2.0.0')
    si.compare_to_reference(cur, ref)
    VBR.version_boundary_report(ref, cur)
    dm.DecisionMetadata.from_dict(json.loads(decision().to_json()))
    scs.StrategyConfigSnapshot.from_dict(snap().to_dict())
    assert rec == decision()


def test_new_modules_stay_dormant():
    code = ('import json, sys; sys.path.insert(0, "."); '
            'import shared.strategy_identity, shared.strategy_config_snapshot, shared.decision_metadata, '
            'shared.strategy_version_boundary; '
            'bad = sorted(m for m in sys.modules if m.split(".")[0] in '
            '("analyzer", "scanner", "signal_engine", "telegram", "trade_tracker", "research", '
            '"asyncpg", "aiohttp", "pandas") or m in ("shared.config", "shared.database", '
            '"shared.evidence_v2")); print(json.dumps(bad))')
    out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
                         env={'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'}, check=True)
    assert json.loads(out.stdout) == []


def test_freeze_artefact_is_only_named_never_opened_or_written():
    modules = (si, scs, dm, VBR)
    writes = re.compile(r"\.write\(|write_text|write_bytes|open\([^)]*['\"][wax+]")
    for module in modules:
        assert not writes.search(inspect.getsource(module)), module.__name__
    mentions = [m.__name__ for m in modules if 'research_freeze.json' in inspect.getsource(m)]
    assert mentions == ['shared.strategy_identity']
    assert inspect.getsource(si).count('research_freeze.json') == 2   # docstring + HISTORICAL_FREEZE
    assert si.HISTORICAL_FREEZE['read'] is False and si.HISTORICAL_FREEZE['recomputed'] is False
