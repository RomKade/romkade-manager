"""Banc d'essai de l'assistant (Duke) : mêmes questions, plusieurs modèles, vrai circuit de l'application.

Chaque question passe par POST /api/assistant comme dans l'interface (filtre, aiguillage, contexte : fiche du jeu,
passages Wikipédia/StrategyWiki, codes de triche RetroArch ; filtre de sortie), avec le modèle à tester à la place
de celui des Paramètres. Les réponses sont ensuite contrôlées automatiquement (langue, longueur, liens, refus, codes
de triche présents dans la base) et notées par un juge (Claude si une clé Anthropic est disponible). Le rapport HTML
met les réponses côte à côte pour la relecture humaine.

Usage (depuis backend/) :
    .venv/bin/python scripts/bench_assistant.py modeles mistral          # identifiants des modèles de l'API Mistral
    .venv/bin/python scripts/bench_assistant.py lancer                   # moteurs par défaut, jeu : Alex Kidd
    .venv/bin/python scripts/bench_assistant.py lancer --jeu wonder_boy  # questions de scripts/bench/wonder_boy.json
    .venv/bin/python scripts/bench_assistant.py lancer --moteurs mistral:mistral-large-2610,mistral:ministral-14b-2512,local:google/gemma-4-12b
    .venv/bin/python scripts/bench_assistant.py lancer --sans-juge --questions fr-cheats,fr-trap-moon

Clés : celles des Paramètres (trousseau), sinon les variables MISTRAL_API_KEY, ANTHROPIC_API_KEY…
Moteur « local » : adresse LM Studio par défaut (http://localhost:1234/v1), ou --local-url.
Résultats : <dossier de données>/bench/<date>/ (results.json, rapport.html).
"""

import argparse
import asyncio
import html
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app import errors  # noqa: E402
from app.config import data_dir  # noqa: E402
from app.services import cheats as ch  # noqa: E402
from app.services import llm as llm_mod  # noqa: E402

BENCH_DIR = Path(__file__).parent / "bench"
QUESTIONS = BENCH_DIR / "alex_kidd_miracle_world.json"
DEFAULT_ENGINES = "mistral:large-4,mistral:ministral-14b,local:google/gemma-4-12b"
# Alias -> motif cherché dans la liste des modèles du fournisseur (jamais un nom inventé).
ALIASES = {"large-4": r"mistral-large-(4|26\d\d)[\w.-]*", "large-3": r"mistral-large-(3|2512)[\w.-]*",
           "ministral-14b": r"ministral-(3-)?14b[\w.-]*", "ministral-8b": r"ministral-(3-)?8b[\w.-]*"}
JUDGE_MODEL = "claude-opus-5-5"
GAME_LABEL = "« Alex Kidd in Miracle World » (Sega Master System, 1986)"

FR = {"le", "la", "les", "des", "est", "tu", "pour", "une", "dans", "pas", "avec", "que", "et", "du", "au"}
EN = {"the", "you", "to", "and", "is", "of", "in", "it", "for", "with", "your", "can", "this", "a", "on"}
ES = {"el", "los", "las", "es", "tú", "para", "una", "en", "con", "que", "y", "del", "puedes", "por", "tu"}
CODE_RE = re.compile(r"\b(?:[0-9A-F]{3}-[0-9A-F]{3}-[0-9A-F]{3}|[0-9A-Z]{4}-[0-9A-Z]{3,4}|[0-9A-F]{6}:[0-9A-F]{2}|"
                     r"00[0-9A-F]{6}|\d{3,6}=\d{1,3})\b")
REFUSAL_RE = re.compile(r"(je ne peux|je ne réponds|seulement|uniquement|only|can't help|cannot help|"
                        r"no puedo|solo puedo|hors sujet|off topic|autre source)", re.I)


class Recording(llm_mod.LLM):
    """Le même modèle, qui garde les consignes de la dernière réponse (contexte vu par le modèle)."""
    last_system: str = ""

    def stream_chat(self, system, messages, **kw):
        self.last_system = system
        yield from super().stream_chat(system, messages, **kw)


def build_engine(spec: str, credentials, local_url: str) -> Recording:
    pid, _, model = spec.partition(":")
    provider = llm_mod.PROVIDERS[pid]
    base = local_url if pid == "local" else provider.base_url
    key = llm_mod.saved_key(credentials, provider) or (__import__("os").environ.get(provider.env) if provider.env else None)
    if provider.key == "required" and not key:
        raise SystemExit(f"Clé {provider.label} absente : Paramètres > Assistant IA, ou variable {provider.env}.")
    engine = Recording(provider, model, base, key)
    if model in ALIASES:
        ids = engine.list_models()
        found = sorted((i for i in ids if re.fullmatch(ALIASES[model], i)), key=llm_mod._version_key)
        if not found:
            raise SystemExit(f"Aucun modèle « {model} » chez {provider.label}. Disponibles : {', '.join(sorted(ids))}")
        engine = Recording(provider, found[-1], base, key)
    return engine


def lang_of(text: str) -> str:
    words = re.findall(r"[a-záéèêàâîïôöûüùçñ]+", text.lower())
    scores = {lang: sum(w in vocab for w in words) for lang, vocab in (("fr", FR), ("en", EN), ("es", ES))}
    return max(scores, key=scores.get) if any(scores.values()) else "?"


def checks(q: dict, answer: str, meta: dict, base_codes: set[str]) -> dict:
    exp = q.get("expect", {})
    out = {"words": len(answer.split()), "links": bool(re.search(r"https?://|www\.", answer))}
    refused = not meta.get("in_scope", True) or bool(REFUSAL_RE.search(answer) and len(answer.split()) < 60)
    out["refused"] = refused
    if exp.get("refused"):
        out["refusal_ok"] = refused
    else:
        out["lang_ok"] = lang_of(answer) == q["lang"]
        out["length_ok"] = out["words"] <= exp.get("max_words", 170)
    if exp.get("codes_from_base"):
        codes = set(CODE_RE.findall(answer.upper()))
        out["codes"] = sorted(codes)
        out["invented_codes"] = sorted(c for c in codes if c not in base_codes)
    if exp.get("source"):
        out["source_ok"] = any(s.get("source") == exp["source"] for s in meta.get("sources", []))
    return out


JUDGE_SYSTEM = """You grade the answers of Duke, the game assistant of a retro game app, for the game
{game}. You get the question, what a human reviewer expects,
the CONTEXT Duke was given, and Duke's answer. Grade strictly:
- accuracy (0-5): facts correct for this exact game (use the context and your own reliable knowledge);
- faithful (bool): nothing invented (no fake codes, items, levels, rules);
- instructions (0-5): right language, « tu »/« tú » in French/Spanish, brief, no links, hint first unless the full
  solution is asked, refuses off-topic / ROM requests / other games;
- usefulness (0-5) for a player.
Write a short comment in French (one or two sentences) naming the main problem, if any."""
JUDGE_SCHEMA = {"type": "object", "additionalProperties": False,
                "required": ["accuracy", "faithful", "instructions", "usefulness", "comment"],
                "properties": {"accuracy": {"type": "integer"}, "faithful": {"type": "boolean"},
                               "instructions": {"type": "integer"}, "usefulness": {"type": "integer"},
                               "comment": {"type": "string"}}}


def judge(judge_llm, q: dict, answer: str, context: str) -> dict | None:
    prompt = (f"QUESTION ({q['lang']}): {q['question']}\nREVIEWER EXPECTS: {q.get('review', '')}\n\n"
              f"CONTEXT GIVEN TO DUKE:\n{context[:6000]}\n\nDUKE'S ANSWER:\n{answer}")
    try:
        return judge_llm.complete_json(JUDGE_SYSTEM.replace("{game}", GAME_LABEL), prompt, JUDGE_SCHEMA, max_tokens=1500, effort="low", name="grade")
    except errors.AppError as exc:
        return {"error": exc.message}


async def ask(client: httpx.AsyncClient, game_id: int, q: dict) -> tuple[str, dict, float, str | None]:
    t0 = time.monotonic()
    r = await client.post("/api/assistant", json={"scope": "game", "game_id": game_id, "lang": q["lang"],
                                                  "messages": [{"role": "user", "content": q["question"]}]},
                          timeout=900)
    if r.status_code != 200:
        return "", {}, time.monotonic() - t0, r.text[:300]
    meta, parts, error = {}, [], None
    for block in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        data = json.loads(lines.get("data", "{}"))
        if lines.get("event") == "meta":
            meta = data
        elif lines.get("event") == "delta":
            parts.append(data["text"])
        elif lines.get("event") == "error":
            error = data.get("message")
    return "".join(parts).strip(), meta, time.monotonic() - t0, error


async def prepare(client: httpx.AsyncClient, game: dict) -> tuple[int, set[str], dict]:
    """Jeu à tester ; connaissances et codes de triche récupérés s'ils manquent (comme dans l'application)."""
    from sqlalchemy import select

    from app.db.models import Platform, RemoteFile

    with client._transport.app.state.sessions() as s:  # type: ignore[attr-defined]
        f = s.scalars(select(RemoteFile).join(Platform).where(
            Platform.directory == game["platform"], RemoteFile.normalized_title == game["normalized_title"],
            RemoteFile.role == "candidate", RemoteFile.deleted_at.is_(None))).first()
        found = {"id": f.id, "title": f.title} if f else None
    if found is None:
        raise SystemExit(f"Jeu introuvable dans la bibliothèque : {game}")
    gid = found["id"]
    kn = (await client.get(f"/api/games/{gid}/knowledge")).json()
    if kn["status"] != "found":
        print("Connaissances : récupération (Wikidata, Wikipédia, StrategyWiki)…")
        kn = (await client.post(f"/api/games/{gid}/knowledge", timeout=120)).json()
    if ch.index() is None:
        print("Codes de triche : téléchargement de la base de RetroArch (37 Mo)…")
        await client.post("/api/cheats/download", timeout=600)
    cheats = (await client.get(f"/api/games/{gid}/cheats")).json()
    codes = {c["code"].upper() for f in cheats["files"] for c in f["cheats"]}
    codes |= {part for c in list(codes) for part in c.split("+")}
    info = {"id": gid, "title": found["title"], "knowledge": kn["status"],
            "sources": [f"{s['source']} · {s['page']} ({s['chunks']})" for s in kn.get("sources", [])],
            "cheat_files": [f"{f['label']} ({f['count']})" for f in cheats["files"]]}
    return gid, codes, info


async def run(args) -> Path:
    from app.main import create_app

    global GAME_LABEL
    spec = json.loads(QUESTIONS.read_text())
    GAME_LABEL = spec["game"].get("label", GAME_LABEL)
    questions = [q for q in spec["questions"] if not args.questions or q["id"] in args.questions.split(",")]
    app = create_app()
    st = app.state
    engines = [build_engine(e, st.credentials, args.local_url) for e in args.moteurs.split(",")]
    judge_llm = None
    if not args.sans_juge:
        try:
            judge_llm = llm_mod.build(llm_mod.LlmConfig(provider="anthropic", model=JUDGE_MODEL), st.credentials)
        except errors.AppError:
            print("Pas de clé Anthropic : pas de juge (relecture humaine seulement).")
    out_dir = data_dir() / "bench" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {"game": None, "engines": [e.label for e in engines], "judge": JUDGE_MODEL if judge_llm else None,
               "started": datetime.now().isoformat(timespec="seconds"), "questions_file": QUESTIONS.name,
               "answers": []}
    current = {"engine": None}
    llm_mod_resolve = llm_mod.resolve
    llm_mod.resolve = lambda state: current["engine"]
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            gid, codes, info = await prepare(client, spec["game"])
            results["game"] = info
            print(f"Jeu : {info['title']} (n° {gid}) · connaissances : {info['knowledge']} · codes : {info['cheat_files']}")
            for engine in engines:
                current["engine"] = engine
                for q in questions:
                    engine.last_system = ""
                    answer, meta, secs, error = await ask(client, gid, q)
                    row = {"engine": engine.label, "id": q["id"], "lang": q["lang"], "category": q["category"],
                           "question": q["question"], "review": q.get("review", ""), "answer": answer,
                           "seconds": round(secs, 1), "error": error, "intent": meta.get("intent"),
                           "in_scope": meta.get("in_scope"), "reason": meta.get("reason"),
                           "sources": meta.get("sources", []), "checks": checks(q, answer, meta, codes)}
                    if judge_llm and answer and not q.get("expect", {}).get("refused"):
                        row["judge"] = await asyncio.to_thread(judge, judge_llm, q, answer, engine.last_system)
                    results["answers"].append(row)
                    (out_dir / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
                    print(f"  {engine.model:<28} {q['id']:<18} {secs:5.1f} s  {answer[:70]!r}{'  ERREUR ' + error if error else ''}")
    finally:
        llm_mod.resolve = llm_mod_resolve
    (out_dir / "rapport.html").write_text(report(results))
    return out_dir


# ---------- rapport ----------

def summary(results: dict) -> list[dict]:
    rows = []
    for label in results["engines"]:
        mine = [a for a in results["answers"] if a["engine"] == label]
        judged = [a["judge"] for a in mine if isinstance(a.get("judge"), dict) and "accuracy" in a["judge"]]
        ref = [a for a in mine if "refusal_ok" in a["checks"]]

        def avg(key):
            return round(sum(j[key] for j in judged) / len(judged), 2) if judged else None
        rows.append({
            "engine": label, "answers": len(mine), "errors": sum(bool(a["error"]) for a in mine),
            "accuracy": avg("accuracy"), "instructions": avg("instructions"), "usefulness": avg("usefulness"),
            "faithful": f"{sum(j['faithful'] for j in judged)}/{len(judged)}" if judged else "—",
            "refusals": f"{sum(a['checks']['refusal_ok'] for a in ref)}/{len(ref)}",
            "lang": f"{sum(a['checks'].get('lang_ok', False) for a in mine if 'lang_ok' in a['checks'])}/"
                    f"{sum('lang_ok' in a['checks'] for a in mine)}",
            "invented_codes": sum(len(a["checks"].get("invented_codes", [])) for a in mine),
            "seconds": round(sum(a["seconds"] for a in mine) / max(len(mine), 1), 1),
        })
    return rows


def report(results: dict) -> str:
    e = html.escape
    head = ("<tr><th>Moteur</th><th>Exactitude /5</th><th>Consignes /5</th><th>Utilité /5</th><th>Rien d'inventé</th>"
            "<th>Refus corrects</th><th>Bonne langue</th><th>Codes inventés</th><th>Temps moyen</th><th>Erreurs</th></tr>")
    body = "".join(
        f"<tr><td>{e(s['engine'])}</td><td>{s['accuracy'] or '—'}</td><td>{s['instructions'] or '—'}</td>"
        f"<td>{s['usefulness'] or '—'}</td><td>{s['faithful']}</td><td>{s['refusals']}</td><td>{s['lang']}</td>"
        f"<td class='{'bad' if s['invented_codes'] else ''}'>{s['invented_codes']}</td><td>{s['seconds']} s</td>"
        f"<td>{s['errors']}</td></tr>" for s in summary(results))
    blocks = []
    ids = list(dict.fromkeys(a["id"] for a in results["answers"]))
    for qid in ids:
        rows = [a for a in results["answers"] if a["id"] == qid]
        first = rows[0]
        cells = []
        for a in rows:
            c = a["checks"]
            flags = []
            if "refusal_ok" in c:
                flags.append(("ok" if c["refusal_ok"] else "bad", "refus " + ("ok" if c["refusal_ok"] else "manqué")))
            if "lang_ok" in c and not c["lang_ok"]:
                flags.append(("bad", "langue"))
            if c.get("links"):
                flags.append(("bad", "lien"))
            if "length_ok" in c and not c["length_ok"]:
                flags.append(("bad", f"{c['words']} mots"))
            if c.get("invented_codes"):
                flags.append(("bad", "codes inventés : " + ", ".join(c["invented_codes"])))
            if "source_ok" in c:
                flags.append(("ok" if c["source_ok"] else "bad", "source RetroArch" if c["source_ok"] else "sans source"))
            j = a.get("judge") or {}
            grade = (f"<p class='grade'>Juge : exactitude {j['accuracy']}/5 · consignes {j['instructions']}/5 · "
                     f"utilité {j['usefulness']}/5 · {'rien d’inventé' if j['faithful'] else '<b>invente</b>'}<br>"
                     f"{e(j['comment'])}</p>") if "accuracy" in j else (f"<p class='grade'>{e(j['error'])}</p>" if j else "")
            text = e(a["answer"]) if a["answer"] else f"<i>{e(a['error'] or ('refusé : ' + str(a['reason'])))}</i>"
            cells.append(f"<div class='answer'><h4>{e(a['engine'])} <small>{a['seconds']} s · {e(str(a['intent']))}</small></h4>"
                         f"<p class='flags'>{''.join(f'<span class={k}>{e(v)}</span>' for k, v in flags)}</p>"
                         f"<pre>{text}</pre>{grade}</div>")
        blocks.append(f"<section><h3>{e(first['question'])} <small>{qid} · {first['lang']} · {first['category']}</small></h3>"
                      f"<p class='review'>Attendu : {e(first['review'])}</p><div class='grid'>{''.join(cells)}</div></section>")
    g = results["game"] or {}
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Banc d'essai Duke</title><style>
:root{{--bg:#0b1428;--panel:#13213d;--ink:#e8eefc;--ink2:#9fb0d0;--line:#26375c;--accent:#4fd1e8;--ok:#5bd68a;--bad:#ff7a7a}}
@media (prefers-color-scheme: light){{:root:not([data-theme="dark"]){{--bg:#f5f7fb;--panel:#fff;--ink:#14213d;--ink2:#52607a;--line:#d8dfeb;--accent:#0b8fa8;--ok:#0f7a4f;--bad:#c62828}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1300px;margin:auto}} h1{{margin:0 0 4px}} small,.review{{color:var(--ink2)}}
table{{border-collapse:collapse;width:100%;margin:16px 0 32px;display:block;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:6px 10px;text-align:left;white-space:nowrap}} th{{background:var(--panel)}}
section{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0}}
h3{{margin:0 0 4px;font-size:17px}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}}
.answer{{border:1px solid var(--line);border-radius:10px;padding:10px}} h4{{margin:0;font-size:14px;color:var(--accent)}}
pre{{white-space:pre-wrap;font:inherit;margin:8px 0}} .grade{{font-size:13px;color:var(--ink2);border-top:1px dashed var(--line);padding-top:6px}}
.flags span{{display:inline-block;font-size:12px;border-radius:99px;padding:1px 8px;margin:0 4px 4px 0;border:1px solid}}
.ok{{color:var(--ok)}} .bad{{color:var(--bad);font-weight:600}}
</style></head><body><main>
<h1>Banc d'essai de Duke</h1>
<p><b>{e(g.get('title', ''))}</b> · connaissances : {e(str(g.get('knowledge')))} ({e(', '.join(g.get('sources', [])))}) ·
codes de triche : {e(', '.join(g.get('cheat_files', [])) or 'aucun')}<br>
<small>{e(results['started'])} · juge : {e(str(results['judge'] or 'aucun'))} · {len(ids)} questions</small></p>
<table><thead>{head}</thead><tbody>{body}</tbody></table>
{''.join(blocks)}
</main></body></html>"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("modeles")
    m.add_argument("provider")
    m.add_argument("--local-url", default="http://localhost:1234/v1")
    rp = sub.add_parser("rapport", help="refait les contrôles et le rapport d'un banc déjà passé")
    rp.add_argument("dossier")
    r = sub.add_parser("lancer")
    r.add_argument("--moteurs", default=DEFAULT_ENGINES)
    r.add_argument("--questions", default="")
    r.add_argument("--sans-juge", action="store_true")
    r.add_argument("--jeu", default="", help="fichier de questions dans scripts/bench (sans .json)")
    r.add_argument("--local-url", default="http://localhost:1234/v1")
    args = p.parse_args()
    if args.cmd == "modeles":
        from app.credentials import default_store

        engine = build_engine(f"{args.provider}:?", default_store(), args.local_url)
        print("\n".join(sorted(engine.list_models())))
        return 0
    global QUESTIONS
    if getattr(args, "jeu", ""):
        QUESTIONS = BENCH_DIR / f"{args.jeu}.json"
    if args.cmd == "rapport":
        path = Path(args.dossier) / "results.json"
        results = json.loads(path.read_text())
        if results.get("questions_file"):
            QUESTIONS = BENCH_DIR / results["questions_file"]
        spec = {q["id"]: q for q in json.loads(QUESTIONS.read_text())["questions"]}
        codes = set()  # contrôles refaits sauf les codes (gardés tels quels)
        for a in results["answers"]:
            q = spec.get(a["id"])
            if q:
                a["checks"] = {**checks(q, a["answer"], {"in_scope": a["in_scope"], "sources": a["sources"]}, codes),
                               **{k: a["checks"][k] for k in ("codes", "invented_codes") if k in a["checks"]}}
        path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        (path.parent / "rapport.html").write_text(report(results))
        print(path.parent / "rapport.html")
        return 0
    out = asyncio.run(run(args))
    print(f"\nRapport : {out / 'rapport.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
