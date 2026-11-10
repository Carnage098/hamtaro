import io
from copy import deepcopy
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw

from cogs.weekly_program import WeeklyProgramCog
from services.tournament_schedule_service import PARIS, weekly_schedule
from services.weekly_program_service import program_description, render_weekly_poster


@pytest.mark.parametrize('scenario', ['empty', 'single', 'standard', 'long', 'four', 'new_year'])
def test_variable_programs_keep_all_text_inside_the_image(monkeypatch, scenario):
    program = weekly_schedule([], datetime(2026, 11, 11, 18, tzinfo=PARIS))
    program['preview'] = True
    if scenario == 'empty':
        program['slots'] = []
    elif scenario == 'single':
        program['slots'] = program['slots'][:1]
    elif scenario == 'long':
        program['slots'][0]['format'] = 'Tournoi spécial de fin de saison — édition communautaire des duellistes'
        program['slots'][0]['platform'] = 'YGO Omega et rencontre communautaire sur le serveur Fun Row'
        program['slots'][0]['code'] = 'IDENTIFIANT' * 9
    elif scenario == 'four':
        program['slots'] += deepcopy(program['slots'])
        for slot, status in zip(program['slots'], ['Annulé', 'Complet', 'En cours', 'Inscriptions closes']):
            slot['status_label'] = status
    elif scenario == 'new_year':
        program.update(monday=date(2026, 12, 28), sunday=date(2027, 1, 3))
    extents = []
    original = ImageDraw.ImageDraw.text

    def record_text(draw, xy, text, *args, **kwargs):
        extents.append(draw.textbbox(xy, text, font=kwargs.get('font'),
                                    anchor=kwargs.get('anchor'), spacing=kwargs.get('spacing', 4)))
        return original(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', record_text)
    content = render_weekly_poster(program)
    image = Image.open(io.BytesIO(content))
    image.verify()
    assert image.width == 1080
    assert len(content) < 8_000_000
    assert extents
    assert all(0 <= left <= right <= image.width and 0 <= top <= bottom <= image.height
               for left, top, right, bottom in extents)
    if scenario == 'standard':
        assert image.height > image.width


@pytest.mark.asyncio
async def test_preview_contains_announcement_and_never_calls_publication(monkeypatch):
    monkeypatch.setenv('HAMTARO_WEEKLY_ENABLED', 'true')
    program = weekly_schedule([], datetime(2026, 11, 11, 18, tzinfo=PARIS))
    monkeypatch.setattr('cogs.weekly_program.get_week_program', AsyncMock(return_value=program))
    cog = WeeklyProgramCog(SimpleNamespace(db=object()))
    cog.publish = AsyncMock()
    interaction = SimpleNamespace(guild_id=1, response=SimpleNamespace(defer=AsyncMock()),
                                  followup=SimpleNamespace(send=AsyncMock()))
    await cog.poster.callback(cog, interaction)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    payload = interaction.followup.send.call_args.kwargs
    assert payload['ephemeral'] is True
    assert payload['embed'].description == program_description(program)
    assert payload['embed'].image.url == f"attachment://{payload['file'].filename}"
    assert payload['allowed_mentions'].everyone is False
    Image.open(payload['file'].fp).verify()
    cog.publish.assert_not_awaited()
