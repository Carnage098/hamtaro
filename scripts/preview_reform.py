"""Aperçu local du site, sans connexion Discord ni base de production."""
import sys
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from jinja2 import Environment, FileSystemLoader, select_autoescape
from services.tournament_schedule_service import PARIS, public_schedule, weekly_schedule
from services.weekly_program_service import render_weekly_poster

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 11, 18, tzinfo=PARIS)
# Deux tournois d’exemple, sans donnée personnelle ni lecture de production.
TOURNAMENTS = [dict(id=index+21, code=slot['code'], name=slot['format'], format=slot['format'],
    scheduled_slot_id=slot['id'], status='registration', participant_count=0, max_players=8)
    for index, slot in enumerate(weekly_schedule([], NOW)['slots'])]
PROGRAM = weekly_schedule(TOURNAMENTS, NOW)
PROGRAM['preview'] = True
JINJA = Environment(loader=FileSystemLoader(ROOT/'web/templates'), autoescape=select_autoescape())
SOCIALS = {'discord':'https://discord.gg/ZGUhg8yTZC', 'youtube':'https://www.youtube.com/@jjetgames2869'}

async def page(request):
    template = 'index.html' if request.path == '/tournaments' else 'home.html'
    html = JINJA.get_template(template).render(request=request, social_links=SOCIALS, bot_avatar_url='',
        weekly_program=PROGRAM, current_tournaments=[], open_tournaments=TOURNAMENTS,
        recent_archives=[], schedule=public_schedule(TOURNAMENTS, now=NOW, upcoming_only=True))
    html = html.replace('<body>', '<body><div style="text-align:center;padding:6px;background:#f4c66a;color:#111;font-size:12px">APERÇU DE LA REFONTE · Données de démonstration · Aucun envoi Discord</div>')
    return web.Response(text=html, content_type='text/html')

if __name__ == '__main__':
    (ROOT/'docs/previews/affiche-semaine.png').write_bytes(render_weekly_poster(PROGRAM))
    app=web.Application()
    app.router.add_get('/', page)
    app.router.add_get('/tournaments', page)
    app.router.add_static('/static', ROOT/'web/static')
    web.run_app(app, host='0.0.0.0', port=8765)
