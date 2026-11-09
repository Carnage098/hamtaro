import asyncio
import io
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import discord
import pytest
from discord.ext import commands

from cogs.weekly_program import WeeklyProgramCog
from services.command_compactor import compact_command_tree
from services.database_service import DatabaseService
from services.tournament_schedule_service import (PARIS, ensure_schedule_tournaments, load_schedule,
    public_schedule, registration_error, registration_window, weekly_schedule)
from services.weekly_program_service import init_weekly_schema, publication_due, render_weekly_poster


def test_rollover_and_alternating_weekends():
    schedule = load_schedule(datetime(2027, 1, 1, tzinfo=PARIS))
    slots = [s for m in schedule['months'] for s in m['slots'] if s['id'].startswith('auto-')]
    assert len({s['id'] for s in slots}) == len(slots)
    assert len({s['code'] for s in slots}) == len(slots)
    for i in range(0, len(slots), 2):
        pair = slots[i:i+2]
        assert len(pair) == 2
        assert sum(s['format'] == 'Classique' for s in pair) == 1
        assert [s['kind'] for s in pair] == (['classic','special'] if i % 4 == 0 else ['special','classic'])
    assert slots[-1]['date'] >= '2027-04-23'


def test_registration_boundaries_and_dst():
    start = {'date':'2026-10-25', 'start':'16:00'}
    opens, closes = registration_window(start)
    assert opens.utcoffset() == timedelta(hours=2)
    assert closes.utcoffset() == timedelta(hours=1)
    slot='2026-11-15-classique'
    assert registration_error(slot, datetime(2026,11,8,15,59,tzinfo=PARIS))
    assert registration_error(slot, datetime(2026,11,8,16,0,tzinfo=PARIS)) is None
    assert registration_error(slot, datetime(2026,11,15,15,29,tzinfo=PARIS)) is None
    assert registration_error(slot, datetime(2026,11,15,15,30,tzinfo=PARIS))


def test_public_program_cancelled_and_past():
    now=datetime(2026,11,11,18,tzinfo=PARIS)
    tournament={'scheduled_slot_id':'2026-11-14-pure','status':'cancelled','max_players':8}
    week=weekly_schedule([tournament], now)
    assert len(week['slots']) == 2
    assert week['slots'][0]['status_label'] == 'Annulé'
    upcoming=public_schedule([tournament], now=now, upcoming_only=True)
    assert all(s['date'] >= '2026-11-11' for m in upcoming['months'] for s in m['slots'])


def test_publication_catchup_and_week_boundaries():
    settings={'enabled':1,'weekday':2,'hour':18,'minute':0}
    assert not publication_due(settings,datetime(2026,11,11,17,59,tzinfo=PARIS))
    assert publication_due(settings,datetime(2026,11,11,18,tzinfo=PARIS))
    assert publication_due(settings,datetime(2026,11,13,23,tzinfo=PARIS))
    assert not publication_due(settings,datetime(2026,11,14,0,tzinfo=PARIS))
    assert not publication_due(settings,datetime(2026,11,16,18,tzinfo=PARIS))


def test_weekly_commands_are_staff_only_after_compaction():
    bot=commands.Bot(command_prefix='!',intents=discord.Intents.none()); bot.db=object()
    cog=WeeklyProgramCog(bot)
    for cmd in cog.get_app_commands(): bot.tree.add_command(cmd)
    compact_command_tree(bot.tree)
    names={cmd.qualified_name for cmd in bot.tree.walk_commands() if isinstance(cmd,discord.app_commands.Command)}
    assert names == {'staff planning affiche','staff planning publier_affiche','staff planning configurer_annonce','staff planning etat_annonce'}
    for cmd in bot.tree.walk_commands():
        if isinstance(cmd,discord.app_commands.Command):
            assert any('staff_only' in check.__qualname__ for check in cmd.checks)


@pytest.mark.asyncio
async def test_create_only_when_open_and_never_duplicate():
    db=DatabaseService(); db.conn=await aiosqlite.connect(':memory:'); db.conn.row_factory=aiosqlite.Row
    try:
        await db.execute('CREATE TABLE tournaments(id INTEGER PRIMARY KEY, guild_id TEXT, code TEXT UNIQUE, name TEXT, format TEXT,max_players INTEGER,status TEXT,created_by TEXT,scheduled_slot_id TEXT UNIQUE)',commit=True)
        assert await ensure_schedule_tournaments(db,'1',now=datetime(2026,11,11,18,tzinfo=PARIS))
        assert await ensure_schedule_tournaments(db,'1',now=datetime(2026,11,11,18,tzinfo=PARIS)) == []
        rows=await db.fetchall('SELECT scheduled_slot_id FROM tournaments')
        assert {r[0] for r in rows} == {'2026-11-14-pure','2026-11-15-classique'}
    finally: await db.close()


@pytest.mark.asyncio
async def test_send_once_and_persist_across_restart(monkeypatch):
    monkeypatch.setenv('HAMTARO_WEEKLY_ENABLED','true')
    db=DatabaseService(); db.conn=await aiosqlite.connect(':memory:'); db.conn.row_factory=aiosqlite.Row
    try:
        await init_weekly_schema(db)
        await db.update('INSERT INTO weekly_program_settings(guild_id,channel_id,enabled) VALUES (?,?,1)',('1','2'))
        channel=MagicMock(spec=discord.TextChannel); channel.id=2; channel.name='annonces'
        channel.permissions_for.return_value=discord.Permissions.all()
        channel.send=AsyncMock(return_value=SimpleNamespace(id=3,jump_url='https://discord.com/channels/1/2/3'))
        guild=SimpleNamespace(me=object(),get_channel=lambda _:channel)
        bot=SimpleNamespace(db=db,get_guild=lambda _:guild,user=SimpleNamespace(id=99))
        program=weekly_schedule([],datetime(2026,11,11,18,tzinfo=PARIS))
        monkeypatch.setattr('cogs.weekly_program.get_week_program',AsyncMock(return_value=program))
        cog=WeeklyProgramCog(bot)
        await asyncio.gather(cog.publish('1'),cog.publish('1'))
        await WeeklyProgramCog(bot).publish('1')
        assert channel.send.await_count == 1
        row=await db.fetchone('SELECT * FROM weekly_program_publications')
        assert row['status'] == 'sent' and row['message_id'] == '3'
    finally: await db.close()


@pytest.mark.asyncio
async def test_unknown_delivery_does_not_resend(monkeypatch):
    monkeypatch.setenv('HAMTARO_WEEKLY_ENABLED','true')
    db=DatabaseService(); db.conn=await aiosqlite.connect(':memory:'); db.conn.row_factory=aiosqlite.Row
    try:
        await init_weekly_schema(db)
        await db.update('INSERT INTO weekly_program_settings(guild_id,channel_id,enabled) VALUES (?,?,1)',('1','2'))
        channel=MagicMock(spec=discord.TextChannel); channel.id=2; channel.permissions_for.return_value=discord.Permissions.all()
        channel.send=AsyncMock(side_effect=TimeoutError('ambiguous delivery'))
        async def history(**kwargs):
            if False: yield None
        channel.history=history
        bot=SimpleNamespace(db=db,get_guild=lambda _:SimpleNamespace(me=object(),get_channel=lambda _:channel),user=SimpleNamespace(id=99))
        monkeypatch.setattr('cogs.weekly_program.get_week_program',AsyncMock(return_value=weekly_schedule([],datetime(2026,11,11,18,tzinfo=PARIS))))
        with pytest.raises(TimeoutError): await WeeklyProgramCog(bot).publish('1')
        with pytest.raises(ValueError, match='incertain'): await WeeklyProgramCog(bot).publish('1')
        assert channel.send.await_count == 1
    finally: await db.close()


def test_poster_is_valid_png_and_supports_empty_week():
    from PIL import Image
    for now in [datetime(2026,11,11,18,tzinfo=PARIS),datetime(2026,1,1,tzinfo=PARIS)]:
        data=render_weekly_poster(weekly_schedule([],now))
        image=Image.open(io.BytesIO(data)); image.verify()
        assert len(data)<8_000_000

@pytest.mark.asyncio
async def test_auto_start_cancels_below_minimum():
    from cogs.tournament_auto_start import TournamentAutoStartCog
    tournament=SimpleNamespace(id=1,status='registration',max_players=8)
    db=SimpleNamespace(get_tournament=AsyncMock(return_value=tournament),fetchone=AsyncMock(return_value={'auto_start_attempted_at':None}))
    cog=TournamentAutoStartCog(SimpleNamespace(db=db))
    cog._claim=AsyncMock(return_value=True); cog._active_players=AsyncMock(return_value=3)
    cog._cancel=AsyncMock(); cog._launch=AsyncMock()
    await cog._process_current(1,{'min_players':4})
    cog._cancel.assert_awaited_once_with(tournament,registered=3,minimum=4,past_due=False)
    cog._launch.assert_not_awaited()

@pytest.mark.asyncio
async def test_late_start_is_cancelled_same_day(monkeypatch):
    from cogs import tournament_auto_start as auto
    class FixedDate(datetime):
        @classmethod
        def now(cls,tz=None): return datetime(2026,11,15,17,tzinfo=PARIS)
    monkeypatch.setattr(auto,'datetime',FixedDate)
    monkeypatch.setattr(auto,'GUILD_ID','')
    db=SimpleNamespace(fetchall=AsyncMock(return_value=[{'id':1,'scheduled_slot_id':'2026-11-15-classique'}]))
    cog=auto.TournamentAutoStartCog(SimpleNamespace(db=db))
    cog._process_past=AsyncMock(); cog._process_current=AsyncMock()
    await cog.auto_start_scan()
    cog._process_past.assert_awaited_once()
    cog._process_current.assert_not_awaited()

@pytest.mark.asyncio
async def test_announcement_refuses_wrong_guild():
    from cogs.tournament_auto_start import TournamentAutoStartCog
    cog=TournamentAutoStartCog(SimpleNamespace(db=object()))
    cog.forced_channel_id='2'
    cog._channel_from_id=AsyncMock(return_value=SimpleNamespace(guild=SimpleNamespace(id=999)))
    assert await cog._announcement_channel(SimpleNamespace(id=1,guild_id='1')) is None


def test_schedule_exceptions_keep_ids_and_cancel_creation(tmp_path, monkeypatch):
    import json
    import services.tournament_schedule_service as service
    raw=json.loads(service.SCHEDULE_PATH.read_text())
    raw['exceptions']={'2026-12-05':{'cancelled':True},'2026-12-06':{'format':'Suisse','start':'17:00'}}
    path=tmp_path/'schedule.json'; path.write_text(json.dumps(raw))
    monkeypatch.setattr(service,'SCHEDULE_PATH',path)
    now=datetime(2026,12,1,tzinfo=PARIS)
    specs=service.schedule_tournament_specs(now=now)
    assert not any(s['scheduled_slot_id']=='auto-2026-12-05' for s in specs)
    modified=next(s for s in specs if s['scheduled_slot_id']=='auto-2026-12-06')
    assert modified['start']=='17:00' and modified['structure']=='swiss'
