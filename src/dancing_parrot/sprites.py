"""Side-view pixel art for the macaw, one sprite per body part.

Every character is one pixel whose value is a colour key, ``.`` is
transparent. ``model.py`` inflates these profiles into 3D.
"""

from __future__ import annotations

TRANSPARENT = "."

# Colour keys: B blue, D dark blue, G green, W white, K black, Y yellow,
# F grey, P pink (tongue).
HEAD: tuple[str, ...] = (
    r".........BBBB.........",
    r".......BBBBBGGG.......",
    r"......BBBBBGGGWKK.....",
    r".....BBBBBGWWWWKKKK...",
    r".....BBBBWWWKWWKKKKK..",
    r".....BBBBWWWWWWKKKKKK.",
    r".....BBBBWKWKWWKK.KKK.",
    r".....BBBBWWKWKWKK...K.",
    r"....BBBBBWWWWWKKK.....",
    r"....BBBBBYYYYK........",
)

# The same head singing: the lower mandible drops and the tongue shows.
HEAD_SINGING: tuple[str, ...] = (
    r".........BBBB.........",
    r".......BBBBBGGG.......",
    r"......BBBBBGGGWKK.....",
    r".....BBBBBGWWWWKKKK...",
    r".....BBBBWWWKWWKKKKK..",
    r".....BBBBWWWWWWKKKKKK.",
    r".....BBBBWKWKWWK..KKK.",
    r".....BBBBWWKWKWKPP..K.",
    r"....BBBBBWWWWWKKKK....",
    r"....BBBBBYYYYKKK......",
)

# A slim, slightly slanted body: macaws are long and lean, not round.
BODY: tuple[str, ...] = (
    r"....BBBBBYYYY......",
    r"....BBBBBYYYYY.....",
    r"....BBBBBYYYYY.....",
    r"....BBBBYYYYYY.....",
    r"...BBBBBYYYYYY.....",
    r"...BBBBBYYYYY......",
    r"...BBBBYYYYYY......",
    r"...BBBBYYYYY.......",
    r"..BBBBBYYYYY.......",
    r"..BBBBYYYYY........",
    r"..BBBBYYYYY........",
    r"..BBBBYYYY.........",
    r"..BBBBYYY..........",
    r"...BBBYY...........",
)

# The long, tapering tail is what makes a macaw look like a macaw.
TAIL: tuple[str, ...] = (
    r"...DDBBB",
    r"...DDBBB",
    r"..DDBBB.",
    r"..DDBBB.",
    r"..DDBB..",
    r"..DDBB..",
    r".DDBB...",
    r".DDBB...",
    r".DDB....",
    r".DDB....",
    r"DDB.....",
    r"DDB.....",
    r"DB......",
    r"DB......",
    r"D.......",
    r"D.......",
)

WING_FOLDED: tuple[str, ...] = (
    r"...DDD..",
    r"..DDDDD.",
    r"..DDDDD.",
    r"..DDDDD.",
    r"..DDDDD.",
    r"..DDDDB.",
    r".DDDDDB.",
    r".DDDDB..",
    r".DDDDB..",
    r".DDDB...",
    r".DDDB...",
    r"DDDB....",
    r"DDD.....",
    r"DD......",
    r"DD......",
    r"D.......",
)

WING_RAISED: tuple[str, ...] = (
    r"D........",
    r"DD.......",
    r".DDD.....",
    r".DDDD....",
    r"..DDDDD..",
    r"...DDDDD.",
    r"...DDDDB.",
    r"....DDDB.",
    r"....DDB..",
    r"....DDB..",
)

# Alternating feet: the parrot lifts one foot, then the other.
FEET: tuple[tuple[str, ...], ...] = (
    (
        r".......F..F...",
        r"......FFF.F...",
        r"..........FFF.",
    ),
    (
        r".......F..F...",
        r".......F.FFF..",
        r"......FFF.....",
    ),
)
