"""pg_hba.conf login scoping for v3 (hba/pg_hba.tsb.v3.snippet). DISPOSABLE TEST CLUSTER ONLY, after the snippet has
been inserted before the final `host all all all scram-sha-256` line and the configuration reloaded.
Network logins: tsb_net_group members reach trading_signals only; backup, migrator and research are rejected on the
network everywhere; the admin and the other projects' roles are unaffected."""
import os
import secrets

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio
HOST = os.environ['TSB_PGHOST']
PW = {k[7:].lower(): v for k, v in os.environ.items() if k.startswith('TSB_PW_')}
NET = ('tsb_scanner', 'tsb_analyzer', 'tsb_signal_engine', 'tsb_telegram', 'tsb_tracker')
LOCAL_ONLY = ('tsb_backup', 'tsb_migrator')
NOLOGIN_NET = ('tsb_learner', 'tsb_dashboard_ro')          # in tsb_net_group, but NOLOGIN until approved
DBS = ('trading_signals', 'postgres', 'wishlist_test', 'xsch', 'wishlist', 'owner_stage')
OTHERS = {'xsch_user': 'xsch', 'wishlist_user': 'wishlist', 'wishlist_test_role': 'wishlist_test', 'shared_pg_backup': 'postgres'}
REJECT = asyncpg.exceptions.InvalidAuthorizationSpecificationError


async def connect(role, db, password):
    return await asyncpg.connect(host=HOST, user=role, password=password, database=db)


@pytest.mark.parametrize('db', DBS)
@pytest.mark.parametrize('role', NET)
async def test_runtime_roles_reach_trading_signals_only(role, db):
    if db == 'trading_signals':
        c = await connect(role, db, PW[role])
        assert await c.fetchval('SELECT current_user') == role
        await c.close()
    else:
        with pytest.raises(REJECT):
            await connect(role, db, PW[role])


@pytest.mark.parametrize('db', DBS)
@pytest.mark.parametrize('role', LOCAL_ONLY + ('tsb_research_ro',))
async def test_backup_migrator_research_rejected_on_the_network(role, db):
    with pytest.raises(REJECT):
        await connect(role, db, PW[role])


@pytest.mark.parametrize('role', NOLOGIN_NET)
async def test_nologin_network_roles_still_refused(role):
    with pytest.raises(REJECT):                                # pg_hba allows; NOLOGIN refuses
        await connect(role, 'trading_signals', PW[role])


@pytest.mark.parametrize('db', DBS)
async def test_admin_network_login_unchanged(db):
    c = await connect('trading_signal_bot', db, PW['trading_signal_bot'])
    await c.close()


async def test_other_projects_roles_unaffected():
    admin = await connect('trading_signal_bot', 'postgres', PW['trading_signal_bot'])
    try:
        for role, db in OTHERS.items():
            pw = secrets.token_urlsafe(24)                     # disposable cluster only; never printed
            await admin.execute(f"ALTER ROLE {role} PASSWORD '{pw}'")
            c = await connect(role, db, pw)
            assert await c.fetchval('SELECT current_user') == role
            await c.close()
    finally:
        await admin.close()
