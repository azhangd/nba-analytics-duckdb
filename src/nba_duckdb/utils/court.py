"""NBA court geometry constants and zone mapping."""

# Court dimensions (in feet)
COURT_LENGTH = 94
COURT_WIDTH = 50
HALF_COURT_LENGTH = 47

# NBA API coordinate system: origin at basket, tenths of feet
# x: -250 to 250 (left to right)
# y: -50 to ~420 (baseline to halfcourt)
NBA_API_SCALE = 10  # coordinates are in tenths of feet

# Three-point line distance (feet)
THREE_POINT_DISTANCE = 23.75  # feet from basket (above the break)
CORNER_THREE_DISTANCE = 22.0  # feet from basket (corner)
CORNER_THREE_Y_THRESHOLD = 92.5  # y-coordinate threshold for corner 3s

# Restricted area radius
RESTRICTED_AREA_RADIUS = 4.0  # feet

# Paint dimensions
PAINT_WIDTH = 16  # feet
PAINT_LENGTH = 19  # feet (free throw line to baseline)

# Shot zone definitions (matching NBA.com zones)
SHOT_ZONES = {
    "Restricted Area": {"max_distance": 4.0},
    "In The Paint (Non-RA)": {"max_distance": 8.0, "in_paint": True},
    "Mid-Range": {"min_distance": 8.0, "max_distance_fn": "three_point_line"},
    "Left Corner 3": {"beyond_arc": True, "corner": "left"},
    "Right Corner 3": {"beyond_arc": True, "corner": "right"},
    "Above the Break 3": {"beyond_arc": True, "corner": None},
    "Backcourt": {"backcourt": True},
}

# Reference team ID used by court visual helpers.
REFERENCE_TEAM_ID = 1610612747

# All NBA team IDs for expansion
NBA_TEAM_IDS = {
    1610612737: "ATL", 1610612738: "BOS", 1610612751: "BKN", 1610612766: "CHA",
    1610612741: "CHI", 1610612739: "CLE", 1610612742: "DAL", 1610612743: "DEN",
    1610612765: "DET", 1610612744: "GSW", 1610612745: "HOU", 1610612754: "IND",
    1610612746: "LAC", 1610612747: "LAL", 1610612763: "MEM", 1610612748: "MIA",
    1610612749: "MIL", 1610612750: "MIN", 1610612740: "NOP", 1610612752: "NYK",
    1610612760: "OKC", 1610612753: "ORL", 1610612755: "PHI", 1610612756: "PHX",
    1610612757: "POR", 1610612758: "SAC", 1610612759: "SAS", 1610612761: "TOR",
    1610612762: "UTA", 1610612764: "WAS",
}
