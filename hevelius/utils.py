
CONSTELLATION_NAMES = {
        "And": "Andromeda",
        "Ant": "Antlia",
        "Aps": "Apus",
        "Aqr": "Aquarius",
        "Aql": "Aquila",
        "Ara": "Ara",
        "Ari": "Aries",
        "Aur": "Auriga",
        "Boo": "Boötes",
        "Cae": "Caelum",
        "Cam": "Camelopardalis",
        "Cnc": "Cancer",
        "Cvn": "Canes Venatici",
        "CMa": "Canis Major",
        "CMi": "Canis Minor",
        "Cap": "Capricornus",
        "Car": "Carina",
        "Cas": "Cassiopeia",
        "Cen": "Centaurus",
        "Cep": "Cepheus",
        "Cet": "Cetus",
        "Cha": "Chamaeleon",
        "Cir": "Circinus",
        "Col": "Columba",
        "Com": "Coma Berenices",
        "CrA": "Corona Australis",
        "CrB": "Corona Borealis",
        "Crv": "Corvus",
        "Crt": "Crater",
        "Cru": "Crux",
        "Cyg": "Cygnus",
        "Del": "Delphinus",
        "Dor": "Dorado",
        "Dra": "Draco",
        "Equ": "Equuleus",
        "Eri": "Eridanus",
        "For": "Fornax",
        "Gem": "Gemini",
        "Gru": "Grus",
        "Her": "Hercules",
        "Hor": "Horologium",
        "Hya": "Hydra",
        "Hyi": "Hydrus",
        "Ind": "Indus",
        "Lac": "Lacerta",
        "Leo": "Leo",
        "LMi": "Leo Minor",
        "Lep": "Lepus",
        "Lib": "Libra",
        "Lup": "Lupus",
        "Lyn": "Lynx",
        "Lyr": "Lyra",
        "Men": "Mensa",
        "Mic": "Microscopium",
        "Mon": "Monoceros",
        "Mus": "Musca",
        "Nor": "Norma",
        "Oct": "Octans",
        "Oph": "Ophiuchus",
        "Ori": "Orion",
        "Oav": "Pavo",
        "Peg": "Pegasus",
        "Per": "Perseus",
        "Phe": "Phoenix",
        "Pic": "Pictor",
        "Psc": "Pisces",
        "PsA": "Piscis Austrinus",
        "Pup": "Puppis",
        "Pyx": "Pyxis",
        "Ret": "Reticulum",
        "Sge": "Sagitta",
        "Sgr": "Sagittarius",
        "Sco": "Scorpius",
        "Scl": "Sculptor",
        "Sct": "Scutum",
        "Ser": "Serpens",
        "Sex": "Sextans",
        "Tau": "Taurus",
        "Tel": "Telescopium",
        "Tri": "Triangulum",
        "TrA": "Triangulum Australe",
        "Tuc": "Tucana",
        "UMa": "Ursa Major",
        "UMi": "Ursa Minor",
        "Vel": "Vela",
        "Vir": "Virgo",
        "Vol": "Volans",
        "Vul": "Vulpecula"
    }


def constellation2abbrev(cons: str) -> str:
    """
    Provides Abbreviation for a full constellation name
    """

    for key in CONSTELLATION_NAMES:
        if cons.lower() == CONSTELLATION_NAMES[key].lower():
            return key

    raise ValueError(f"Constellation {cons} not found")


def abbrev2constellation(cons: str) -> str:
    """
    Provides full constellation name for an abbreviation
    """

    if cons in CONSTELLATION_NAMES:
        return CONSTELLATION_NAMES[cons]

    raise ValueError(f"Constellation {cons} not found")


def deg2rah(ra: float) -> str:
    """Converts Right Ascension specified in degrees (0..359) to hour
    (0..23.59)"""

    h = int(ra / 15)
    m = int((ra - h * 15) * 4)

    return f"{h}h{m:02d}m ({ra:.02f}deg)"


def hm2deg(h: int, m: int) -> float:
    """Converts Right Ascension expressed as h:m to degrees. This function
    was written by ChatGPT (☉_☉)"""
    return (h + m/60) * 15


def parse_ra(ra: str) -> float:
    """Parses Right Ascension in text format to float. Supported formats:
    - 11 22 33
    - 11 22
    - 11h22m33s
    - 11h22m33.4s
    - 11.2345 (fractional)

    returns float (0.0 ... 23.999)
    """
    ra = ra.strip()
    ra = ra.replace("h", " ")
    ra = ra.replace("m", " ")
    ra = ra.replace("s", " ")
    tokens = ra.split()

    if len(tokens) == 3:  # if three tokens, assume hh mm ss
        hrs = float(tokens[0])
        mins = float(tokens[1])
        secs = float(tokens[2])
        ra_float = hrs + mins/60 + secs/3600
    elif len(tokens) == 2:  # if two tokens, assume hh mm
        hrs = float(tokens[0])
        mins = float(tokens[1])
        ra_float = hrs + mins/60
    else:  # otherwise assume hh.mmmm format
        ra_float = float(tokens[0])

    if ra_float < 0.0 or ra_float >= 24.0:
        raise ValueError(f"{ra} is not a valid right ascension value (0.0 ... 23.99999)")

    return ra_float


def parse_dec(dec: str) -> float:
    """
    Parses Right Ascension in text format to float. Supported formats:
    -  11 22 33
    - +11 22 33
    - -11 22 33
    - 11 22
    - 11d22m33s
    - 11d22m33.4s
    - 11.2345 (fractional)
    """

    dec = dec.strip()
    dec = dec.replace("d", " ")
    dec = dec.replace("m", " ")
    dec = dec.replace("s", " ")
    tokens = dec.split()

    if len(tokens) == 3:  # if three tokens, assume hh mm ss
        hrs = abs(float(tokens[0]))
        mins = float(tokens[1])
        secs = float(tokens[2])
        dec_float = hrs + mins/60 + secs/3600
        if float(tokens[0]) < 0:
            dec_float = - dec_float
    elif len(tokens) == 2:  # if two tokens, assume hh mm
        hrs = abs(float(tokens[0]))
        mins = float(tokens[1])
        dec_float = hrs + mins/60
        if float(tokens[0]) < 0:
            dec_float = - dec_float
    else:  # otherwise assume hh.mmmm format
        dec_float = float(tokens[0])

    if dec_float > 90 or dec_float < -90:
        raise ValueError(f"{dec} is not the right declination value (-90 ... 90)")

    return dec_float


def format_ra(ra: float) -> str:
    """Formats Right Ascension as HH MM SS, returns str"""
    h = int(ra)

    min = int((ra - h)*60)

    sec = (ra - h - min/60)*3600

    return f"{h:02} {min:02} {sec:04.1f}"


def format_dec(decl: float) -> str:
    """Formats declination as DD MM SS, returns str"""
    minus = decl < 0

    decl = abs(decl)

    h = int(decl)

    min = int((decl - h)*60)

    sec = (decl - h - min/60)*3600
    if minus:
        h = -h
        # need to have a bit wider hour (extra char for minus)
        return f"{h:03} {min:02} {sec:04.1f}"
    else:
        return f"{h:02} {min:02} {sec:04.1f}"
