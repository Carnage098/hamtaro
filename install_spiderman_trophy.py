#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, py_compile, re, shutil
from datetime import datetime
from pathlib import Path

PACK_VERSION="1.0"
TROPHY_ID="HT-003"
HERE=Path(__file__).resolve().parent
ROOT=Path.cwd()
MODEL_SOURCE=HERE/"ht-003-spiderman-champion.glb"
MODEL_TARGET=ROOT/"web/static/models/trophies/ht-003-spiderman-champion.glb"
CSS_START="/* ===== HAMTARO SPIDERMAN TROPHY START ===== */"
CSS_END="/* ===== HAMTARO SPIDERMAN TROPHY END ===== */"

def args():
    p=argparse.ArgumentParser(description="Installer le trophée Spiderman HT-003")
    p.add_argument("--check",action="store_true")
    return p.parse_args()

def require_repo():
    required=[ROOT/"cogs/end_tournament.py",ROOT/"cogs/public_website.py",ROOT/"services/trophy_service.py",ROOT/"web/data/trophies.json",ROOT/"web/templates/trophies.html",ROOT/"web/templates/formats.html",ROOT/"web/static/style.css"]
    missing=[p for p in required if not p.exists()]
    if missing:
        print("❌ Lance ce script depuis la racine du dépôt Hamtaro.")
        for p in missing: print(" -",p)
        raise SystemExit(1)
    if not MODEL_SOURCE.exists() or MODEL_SOURCE.read_bytes()[:4] != b"glTF":
        raise SystemExit("❌ Modèle GLB HT-003 invalide ou absent.")

def trophy_payload():
    return {"id":"HT-003","number":3,"name":"Spiderman Champion","title":"Le trophée du tournoi Spiderman","tagline":"Le masque de l'araignée couronne son champion.","description":"Trophée officiel réservé au vainqueur du tournoi Spiderman. Il rejoint la collection permanente Hamtaro et sera attribué automatiquement lorsque ce tournoi sera terminé.","legacy":"HT-003 conservera le nom du champion, son deck, le format et l'identifiant réel du tournoi Spiderman dans l'histoire compétitive Hamtaro.","rarity":"LÉGENDAIRE — SPIDERMAN","classification":"Tournoi spécial","edition":"1/1","distinction":"Champion Spiderman","status":"Trophée officiel — à venir","model_path":"/static/models/trophies/ht-003-spiderman-champion.glb?v=20260816-spiderman-1","model_size_mb":None,"poster_path":None,"holder_discord_id":None,"holder_name":None,"deck":None,"format":None,"tournament_name":"Spiderman","tournament_id":None,"tournament_code":None,"awarded_at":None,"badge":"Champion Spiderman","badge_description":"Une distinction unique réservée au vainqueur du tournoi Spiderman.","source_master":"Meshy_AI_trophy_spiderman_mask_0816010747_image-to-3d-texture.glb","web_build":"original-glb","award_match":["Spiderman","Spider-Man","Spider Man"]}

def patch_catalog(text):
    data=json.loads(text); trophies=data.setdefault("trophies",[]); wanted=trophy_payload()
    for i,item in enumerate(trophies):
        if str(item.get("id","")).upper()==TROPHY_ID:
            merged=dict(item); merged.update(wanted); trophies[i]=merged; break
    else: trophies.append(wanted)
    trophies.sort(key=lambda x:int(x.get("number",999999)))
    return json.dumps(data,ensure_ascii=False,indent=2)+"\n"

def patch_trophy_service(text):
    line="from services.spiderman_trophy_award_service import SpidermanTrophyAwardService\n"
    if line not in text:
        anchor="from services.trophy_award_service import TrophyAwardService\n"
        if anchor not in text: raise RuntimeError("TrophyAwardService introuvable")
        text=text.replace(anchor,anchor+line,1)
    line="        self.spiderman_awards = SpidermanTrophyAwardService()\n"
    if line not in text:
        anchor="        self.awards = TrophyAwardService(bot)\n"
        if anchor not in text: raise RuntimeError("Initialisation TrophyAwardService introuvable")
        text=text.replace(anchor,anchor+line,1)
    line="        awards.update(await self.spiderman_awards.all_awards())\n"
    if line not in text:
        anchor="        awards = await self.awards.all_awards()\n"
        if anchor not in text: raise RuntimeError("Chargement des attributions introuvable")
        text=text.replace(anchor,anchor+line,1)
    line='            item["tournament_code"] = award.get("tournament_code") or item.get("tournament_code")\n'
    if line not in text:
        anchor='            item["tournament_id"] = award.get("tournament_id")\n'
        if anchor not in text: raise RuntimeError("Overlay tournament_id introuvable")
        text=text.replace(anchor,anchor+line,1)
    return text

def patch_end(text):
    line="from services.spiderman_trophy_award_service import SpidermanTrophyAwardService\n"
    if line not in text:
        anchor="from utils.permissions import staff_only\n"
        if anchor not in text: raise RuntimeError("staff_only introuvable")
        text=text.replace(anchor,anchor+line,1)
    line="        self.spiderman_trophy_awards = SpidermanTrophyAwardService()\n"
    if line not in text:
        anchor="        self.bot = bot\n"
        if anchor not in text: raise RuntimeError("self.bot introuvable")
        text=text.replace(anchor,anchor+line,1)
    marker="spiderman_trophy_award = await self.spiderman_trophy_awards.award_if_matching_tournament"
    if marker not in text:
        block="        await self._finish_tournament(\n            tournament_id=tournament_id,\n            winner_id=winner_id,\n            winner_name=winner_name,\n        )\n"
        if block not in text: raise RuntimeError("_finish_tournament introuvable")
        addition=block+"        spiderman_trophy_award = await self.spiderman_trophy_awards.award_if_matching_tournament(\n            tournament,\n            winner_id,\n            winner_name,\n        )\n"
        text=text.replace(block,addition,1)
    trophy_block="        if spiderman_trophy_award is not None:\n            embed.add_field(\n                name=\"🕷️ Trophée HT-003\",\n                value=\"Le trophée **Spiderman Champion** a été attribué automatiquement au vainqueur.\",\n                inline=False,\n            )\n"
    if trophy_block not in text:
        anchor="        if distribution:\n"
        if anchor not in text: raise RuntimeError("Zone embed introuvable")
        text=text.replace(anchor,trophy_block+anchor,1)
    return text

def patch_trophies(text): return text.replace("Découvrir HT-001 en 3D","Découvrir {{ trophy.id }} en 3D")

def preview():
    return """    <!-- HAMTARO SPIDERMAN TROPHY PREVIEW START -->
    <article class=\"format-trophy-preview\" aria-label=\"Trophée du tournoi Spiderman\">
        <div class=\"format-trophy-preview-viewer\">
            <model-viewer src=\"/static/models/trophies/ht-003-spiderman-champion.glb?v=20260816-spiderman-1\" alt=\"Trophée 3D du tournoi Spiderman\" auto-rotate auto-rotate-delay=\"0\" rotation-per-second=\"12deg\" camera-controls shadow-intensity=\"1\" environment-image=\"neutral\" interaction-prompt=\"none\" loading=\"eager\" reveal=\"auto\"></model-viewer>
        </div>
        <div class=\"format-trophy-preview-copy\"><div><span class=\"format-kicker\">TROPHÉE À VENIR · HT-003</span><h2>Champion Spiderman</h2><p>Attribué au vainqueur du futur tournoi Spiderman.</p></div><div class=\"format-trophy-preview-actions\"><button class=\"format-trophy-preview-button\" type=\"button\" data-open-spiderman-trophy>Agrandir</button><a class=\"format-trophy-preview-button\" href=\"/trophies/ht-003\">Fiche trophée</a></div></div>
    </article>
    <!-- HAMTARO SPIDERMAN TROPHY PREVIEW END -->"""

def patch_formats(text):
    if "HAMTARO SPIDERMAN TROPHY PREVIEW START" not in text:
        anchor="    {% endfor %}\n</section>"
        if anchor not in text: raise RuntimeError("format-grid introuvable")
        text=text.replace(anchor,"    {% endfor %}\n"+preview()+"\n</section>",1)
    if "data-spiderman-trophy-dialog" not in text:
        dialog="""
<dialog class=\"spiderman-trophy-dialog\" data-spiderman-trophy-dialog><div class=\"spiderman-trophy-dialog-head\"><strong>HT-003 · Champion Spiderman</strong><button class=\"spiderman-trophy-dialog-close\" type=\"button\" data-close-spiderman-trophy aria-label=\"Fermer\">×</button></div><model-viewer src=\"/static/models/trophies/ht-003-spiderman-champion.glb?v=20260816-spiderman-1\" alt=\"Trophée Spiderman agrandi\" auto-rotate auto-rotate-delay=\"0\" rotation-per-second=\"12deg\" camera-controls shadow-intensity=\"1.15\" environment-image=\"neutral\" interaction-prompt=\"auto\"></model-viewer></dialog>
<script type=\"module\" src=\"https://unpkg.com/@google/model-viewer/dist/model-viewer.min.js\"></script>
<script>(()=>{const d=document.querySelector('[data-spiderman-trophy-dialog]'),o=document.querySelector('[data-open-spiderman-trophy]'),c=document.querySelector('[data-close-spiderman-trophy]');o?.addEventListener('click',()=>d?.showModal());c?.addEventListener('click',()=>d?.close());d?.addEventListener('click',e=>{if(e.target===d)d.close()})})();</script>
"""
        if "{% endblock %}" not in text: raise RuntimeError("endblock introuvable")
        text=text.replace("{% endblock %}",dialog+"\n{% endblock %}",1)
    return text

def patch_website(text):
    line="from services.trophy_routes import register_trophy_routes\n"
    if line not in text:
        for anchor in ["from services.banlist_routes import register_banlist_routes\n","from services.site_experience_routes import register_site_experience_routes\n"]:
            if anchor in text: text=text.replace(anchor,anchor+line,1); break
        else: raise RuntimeError("Imports du site introuvables")
    if "register_trophy_routes(" not in text:
        anchor='        application.router.add_get("/favicon.ico", self.favicon)\n'
        if anchor not in text: raise RuntimeError("Routes site introuvables")
        text=text.replace(anchor,"        register_trophy_routes(application, self)\n"+anchor,1)
    return text

def patch_css(text,block):
    if CSS_START in text and CSS_END in text:
        return re.sub(re.escape(CSS_START)+r".*?"+re.escape(CSS_END),block.strip(),text,count=1,flags=re.S)
    return text.rstrip()+"\n\n"+block.strip()+"\n"

def main():
    a=args(); require_repo()
    paths={"catalog":ROOT/"web/data/trophies.json","trophy":ROOT/"services/trophy_service.py","end":ROOT/"cogs/end_tournament.py","trophies":ROOT/"web/templates/trophies.html","formats":ROOT/"web/templates/formats.html","website":ROOT/"cogs/public_website.py","style":ROOT/"web/static/style.css"}
    old={k:p.read_text(encoding="utf-8") for k,p in paths.items()}
    new={"catalog":patch_catalog(old["catalog"]),"trophy":patch_trophy_service(old["trophy"]),"end":patch_end(old["end"]),"trophies":patch_trophies(old["trophies"]),"formats":patch_formats(old["formats"]),"website":patch_website(old["website"]),"style":patch_css(old["style"],(HERE/"spiderman_trophy.css").read_text(encoding="utf-8"))}
    print("🕷️ HT-003 Spiderman · vérification OK")
    print(f"✅ Modèle : {MODEL_SOURCE.stat().st_size/(1024*1024):.1f} Mo")
    print("✅ /trophies + /formats + attribution /end_tournament prêts")
    if a.check: print("Mode --check : aucune modification effectuée."); return 0
    backup=ROOT/f".spiderman_trophy_backup_{datetime.now().strftime('%Y%m%d-%H%M%S')}"; backup.mkdir(parents=True)
    touched=[]
    def save(p):
        if p.exists():
            q=backup/p.relative_to(ROOT); q.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,q)
    try:
        st=ROOT/"services/spiderman_trophy_award_service.py"; save(st); shutil.copy2(HERE/"spiderman_trophy_award_service.py",st); touched.append(st)
        MODEL_TARGET.parent.mkdir(parents=True,exist_ok=True); save(MODEL_TARGET); shutil.copy2(MODEL_SOURCE,MODEL_TARGET); touched.append(MODEL_TARGET)
        for k,p in paths.items():
            if old[k]!=new[k]: save(p); p.write_text(new[k],encoding="utf-8"); touched.append(p); print("✅",p.relative_to(ROOT))
        for p in [st,paths["trophy"],paths["end"],paths["website"]]: py_compile.compile(str(p),doraise=True)
        data=json.loads(paths["catalog"].read_text(encoding="utf-8")); assert sum(1 for x in data["trophies"] if x.get("id")==TROPHY_ID)==1
    except Exception as e:
        print("❌",e); print("♻️ restauration...")
        for f in backup.rglob("*"):
            if f.is_file(): q=ROOT/f.relative_to(backup); q.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(f,q)
        for p in touched:
            if not (backup/p.relative_to(ROOT)).exists() and p.exists(): p.unlink()
        return 1
    print("✅ Installation terminée. HT-003 est lié au futur tournoi Spiderman.")
    return 0

if __name__=="__main__": raise SystemExit(main())
