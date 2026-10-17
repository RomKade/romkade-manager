"""Sous-genres : « Sport » -> Football, Golf, Basket… ; « Course » -> Formule 1, Moto…

Déduits, dans l'ordre :
1. des catégories d'origine des sources (genre_detail : libretro, catver.ini ; et la catégorie OpenVGDB, souvent
   plus fine : « Sports,Traditional,Golf,Sim ») ;
2. à défaut, de mots du titre (« NBA Jam » -> basket, « Tony Hawk's Pro Skater » -> skate, « FIFA 98 » -> football).
La première règle qui correspond gagne : l'ordre des règles compte (« Tecmo Bowl » est du football américain,
pas du bowling). Clés stables « genre.sous-genre » ; libellés traduits dans l'interface (common.subgenre.*).
"""

import re

# genre -> [(clé, libellé français, motif dans les catégories d'origine, motif dans le titre)]
SUBGENRES: dict[str, list[tuple[str, str, str | None, str | None]]] = {
    "sport": [
        ("foot_us", "Football américain", r"american football|football(?!.*soccer)",
         r"\bnfl\b|madden|tecmo bowl|super bowl|\bqb\b|quarterback|gridiron|joe montana|john elway|ncaa football"),
        ("football", "Football", r"soccer",
         r"soccer|fifa|striker|world cup|kick ?off|sensible|winning eleven|pro evolution|\bgoal\b|champions league|"
         r"euro 9\d|football|futbol|fútbol"),
        ("basket", "Basket", r"basketball", r"basket|\bnba\b|hoops?\b|\bdunk|slam ?n|\bjam\b|street ball|streetball"),
        ("baseball", "Baseball", r"baseball",
         r"baseball|\bmlb\b|bases loaded|base wars|home run|world series|\brbi\b|r\.b\.i|pennant|batter up|stadium"),
        ("hockey", "Hockey", r"hockey", r"hockey|\bnhl\b|blades of steel"),
        ("golf", "Golf", r"golf", r"golf|\bputt|birdie|\bpga\b|\blinks\b"),
        ("tennis", "Tennis", r"tennis", r"tennis|wimbledon|smash court|davis cup|grand slam"),
        ("catch", "Catch", r"wrestl", r"wrestl|\bwwf\b|\bwwe\b|\bwcw\b|\becw\b|smackdown|royal rumble|wrestlemania|fire pro|lucha"),
        ("boxe", "Boxe", r"boxing|boxer", r"boxing|boxer|punch-?out|title fight|fight night|toughman|foreman|tyson"),
        ("hiver", "Sports d'hiver", r"ski|snow|winter|ice skat|bobsled|curling",
         r"\bski|snowboard|winter|slalom|bobsle|cool boarders|1080|curling"),
        ("glisse", "Skate, BMX et roller", r"skate|bmx|roller|extreme", r"skate|tony hawk|\bbmx\b|thrasher|x-?games|aggressive inline|roller"),
        ("nautique", "Sports nautiques", r"surf|water|jet ?ski|swim|boat", r"surf|jet ?ski|wave race|water ski|swim"),
        ("peche", "Pêche et chasse", r"fish|hunt|nature", r"fish|\bbass\b|angler|hunt|deer|duck"),
        ("athletisme", "Athlétisme et JO", r"olympic|track & field|track and field|decathlon|athlet",
         r"olympi|decathlon|track (&|and) field|summer games|hyper sports|athlet|sydney 2000|nagano"),
        ("billard", "Billard", r"pool|billiard|snooker", r"\bpool\b|billiard|snooker|hustler"),
        ("bowling", "Bowling", r"bowling", r"bowling|\bbowl\b|ten ?pin"),
        ("volley", "Volley-ball", r"volley", r"volley"),
        ("equitation", "Courses hippiques", r"horse", r"horse|derby|jockey|equestr|stallion"),
        ("autres", "Autres sports", r".", None),
    ],
    "course": [
        ("f1", "Formule 1", r"formula|\bf1\b|grand prix", r"formula|\bf-?1\b|grand prix|\bgp\b|pole position|\bindy|\bcart\b"),
        ("moto", "Moto", r"motorbike|motorcycle|moto\b|bike", r"moto|motor ?cross|\bbike|superbike|road rash|excite ?bike|enduro|super hang-on|hang-on"),
        ("kart", "Kart", r"kart", r"kart"),
        ("rallye", "Rallye et tout-terrain", r"rally|off-?road", r"rally|off-?road|baja|dakar|monster truck|4x4|truck"),
        ("futur", "Course futuriste", r"futuristic", r"f-?zero|wipe ?out|wipeout|extreme-?g|hover|jet ?moto"),
        ("nautique", "Course sur l'eau", r"water|snow|boat", r"wave race|hydro|boat|jet ?ski|power ?boat"),
        ("voitures", "Voitures", r".", None),
    ],
    "combat": [  # catver « Fighter / 2.5D » : des combats en 2D avec plusieurs plans (Fatal Fury)
        ("3d", "Combat en 3D", r"\b3d\b", r"tekken|virtua fighter|soul ?(blade|calibur)|bloody roar|dead or alive|tobal|bushido blade"),
        ("2d", "Combat en 2D", r".", None),
    ],
    "shmup": [
        ("vertical", "Défilement vertical", r"vertical", None),
        ("horizontal", "Défilement horizontal", r"horizontal|scrolling", None),
        ("autres", "Autres shoot'em up", r".", None),
    ],
    "tir": [
        ("pistolet", "Pistolet et stand de tir", r"light gun|gallery|\bgun\b", r"duck hunt|time crisis|house of the dead|virtua cop|lethal enforcers"),
        ("run_gun", "Run and gun", r"platform / shooter|walking|run.?(and|&|n).?gun|scrolling",
         r"contra|metal slug|gunstar|probotector|run.?n.?gun"),
        ("dessus", "Vue de dessus", r"field|driving vertical|top-?down|overhead", r"commando|ikari|smash tv|mercs"),
        ("vue3", "Vue à la 3e personne", r"3rd person|third person|1st person|first person", None),
        ("autres", "Autres tirs", r".", None),
    ],
    "reflexion": [
        ("blocs", "Chutes de blocs", r"drop|falling|tetris", r"tetris|columns|puyo|dr\.? mario|klax|tetrinet"),
        ("associations", "Associations", r"match", r"bejeweled|zoo keeper|panel de pon|tetris attack|puzzle league"),
        ("bulles", "Tir de bulles", r"toss|shooter", r"puzzle bobble|bust-?a-?move|bubble"),
        ("autres", "Autres réflexions", r".", None),
    ],
}

# Début générique d'une catégorie d'origine, retiré avant de chercher la partie fine.
_PREFIX = re.compile(r"^\s*(miscellaneous|action)?[\s,/]*(sports?|driving|racing|fighter|fighting|shooter|puzzle)?\b[\s,/]*", re.I)

LABELS: dict[str, str] = {f"{g}.{key}": label for g, rules in SUBGENRES.items() for key, label, _, _ in rules}
ORDER: list[str] = list(LABELS)  # ordre d'affichage (celui des règles)
# Libellés anglais et espagnols : recherche dans les trois langues (search.py) ; l'interface a les siens.
OTHER_LABELS: dict[str, tuple[str, str]] = {
    "sport.foot_us": ("American football", "Fútbol americano"), "sport.football": ("Soccer", "Fútbol"),
    "sport.basket": ("Basketball", "Baloncesto"), "sport.baseball": ("Baseball", "Béisbol"),
    "sport.hockey": ("Hockey", "Hockey"), "sport.golf": ("Golf", "Golf"), "sport.tennis": ("Tennis", "Tenis"),
    "sport.catch": ("Wrestling", "Lucha libre"), "sport.boxe": ("Boxing", "Boxeo"),
    "sport.hiver": ("Winter sports", "Deportes de invierno"), "sport.glisse": ("Skateboarding, BMX and rollerblading", "Skate, BMX y patines"),
    "sport.nautique": ("Water sports", "Deportes acuáticos"), "sport.peche": ("Fishing and hunting", "Pesca y caza"),
    "sport.athletisme": ("Athletics and Olympics", "Atletismo y Juegos Olímpicos"), "sport.billard": ("Pool and snooker", "Billar"),
    "sport.bowling": ("Bowling", "Bolos"), "sport.volley": ("Volleyball", "Voleibol"),
    "sport.equitation": ("Horse racing", "Carreras de caballos"), "sport.autres": ("Other sports", "Otros deportes"),
    "course.f1": ("Formula 1", "Fórmula 1"), "course.moto": ("Motorbikes", "Motos"), "course.kart": ("Karting", "Karts"),
    "course.rallye": ("Rally and off-road", "Rally y todoterreno"), "course.futur": ("Futuristic racing", "Carreras futuristas"),
    "course.nautique": ("Water racing", "Carreras acuáticas"), "course.voitures": ("Cars", "Coches"),
    "combat.3d": ("3D fighting", "Lucha en 3D"), "combat.2d": ("2D fighting", "Lucha en 2D"),
    "shmup.vertical": ("Vertical scrolling", "Desplazamiento vertical"),
    "shmup.horizontal": ("Horizontal scrolling", "Desplazamiento horizontal"),
    "shmup.autres": ("Other shoot 'em ups", "Otros shoot 'em up"),
    "tir.pistolet": ("Light gun and shooting gallery", "Pistola y galería de tiro"), "tir.run_gun": ("Run and gun", "Run and gun"),
    "tir.dessus": ("Top-down", "Vista cenital"), "tir.vue3": ("Third-person", "Tercera persona"),
    "tir.autres": ("Other shooters", "Otros disparos"),
    "reflexion.blocs": ("Falling blocks", "Bloques que caen"), "reflexion.associations": ("Matching", "Combinaciones"),
    "reflexion.bulles": ("Bubble shooters", "Disparar burbujas"), "reflexion.autres": ("Other puzzles", "Otros puzles"),
}
_COMPILED = {g: [(f"{g}.{k}", re.compile(d, re.I) if d else None, re.compile(t, re.I) if t else None)
                 for k, _, d, t in rules] for g, rules in SUBGENRES.items()}


def classify(genre: str | None, details: list[str | None], title: str) -> str | None:
    """Sous-genre (« sport.golf ») d'un jeu du genre `genre`, ou None si ce genre n'a pas de sous-genres."""
    rules = _COMPILED.get(genre or "")
    if not rules:
        return None
    # Catégories d'origine : on ne garde que leur partie fine (« Sports,Traditional,Golf » -> « Traditional,Golf »).
    precise = " | ".join(p for p in (_PREFIX.sub("", d) for d in details if d) if p)
    for key, by_detail, by_title in rules:
        if by_detail is not None and by_detail.pattern != "." and precise and by_detail.search(precise):
            return key
    for key, _, by_title in rules:
        if by_title is not None and by_title.search(title):
            return key
    # Repli : la dernière règle (« . ») attrape tout le reste du genre (« Autres sports », « Voitures »…).
    last_key, last_detail, _ = rules[-1]
    return last_key if last_detail is not None and last_detail.pattern == "." else None
