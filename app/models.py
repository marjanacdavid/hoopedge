from pydantic import BaseModel
from typing import List, Optional

class PlayerInput(BaseModel):
    id: int
    name: str
    team: str
    opponent: str
    home: bool
    line: Optional[float] = None
    last5: float
    last10: float
    last20: float
    season: float
    ast_last5: float = 0.0
    ast_last10: float = 0.0
    ast_last20: float = 0.0
    ast_season: float = 0.0
    reb_last5: float = 0.0
    reb_last10: float = 0.0
    reb_last20: float = 0.0
    reb_season: float = 0.0
    minutes: float
    usage: float
    pace_factor: float = 1.0
    defense_factor: float = 1.0
    injury_usage_bump: float = 0.0
    h2h: Optional[float] = None
    h2h_ast: Optional[float] = None
    h2h_reb: Optional[float] = None
    h2h_games: int = 0
    injury_status: str = ""
    injury_bump_pts: float = 0.0
    injury_bump_ast: float = 0.0
    injury_bump_reb: float = 0.0
    injured_teammates: List[str] = []
    lines: dict = {}
    games: list = []
    h2h_log: list = []
    ast_std: float = 0.0
    reb_std: float = 0.0
    tpm_last5: float = 0.0
    tpm_last10: float = 0.0
    tpm_last20: float = 0.0
    tpm_season: float = 0.0
    tpm_std: float = 0.0
    pa_last5: float = 0.0
    pa_last10: float = 0.0
    pa_last20: float = 0.0
    pa_season: float = 0.0
    pa_std: float = 0.0
    team_nick: str = ""
    opp_nick: str = ""
    rest_days: Optional[int] = None
    b2b: bool = False
    three_in_four: bool = False
    opp_b2b: bool = False
    game_total: Optional[float] = None
    spread: Optional[float] = None      # iz perspektive igracevog tima (minus = favorit)
    game_date: str = ""
    game_time: str = ""
    headshot: Optional[str] = None
    source: str = "ESPN"
    recent_std: float = 5.0
    trend: float = 0.0
    usage_source: str = "Estimated"
    opponent_defense: float = 0.0
    expected_pace: float = 0.0
    home_split: Optional[float] = None
    away_split: Optional[float] = None
    leader_score: float = 0.0
    is_leader: bool = False
    position: str = ""                 # ESPN pozicija (PG, SF, C ...)
    pos_group: str = ""                # G / F / C
    defense_pos: dict = {}             # trziste -> faktor odbrane protivnika za tu poziciju (>1 = tezi)
    defense_pos_games: int = 0         # broj utakmica iza tog faktora
    defense_pos_missing: list = []     # [{name, grp, status, share}] ključni protivnički branioci koji ne igraju

class Projection(BaseModel):
    player_id: int
    name: str
    team: str
    opponent: str
    line: Optional[float] = None
    projection: float
    market: str = "PTS"
    stat_last5: float = 0.0
    stat_last10: float = 0.0
    stat_last20: float = 0.0
    stat_season: float = 0.0
    delta: Optional[float] = None
    over_probability: Optional[float] = None
    under_probability: Optional[float] = None
    edge: float = 0
    confidence: str
    confidence_score: float = 0
    model_score: float = 0
    lean: str
    last5: float
    last10: float
    last20: float
    season: float
    ast_last5: float = 0.0
    ast_last10: float = 0.0
    ast_last20: float = 0.0
    ast_season: float = 0.0
    reb_last5: float = 0.0
    reb_last10: float = 0.0
    reb_last20: float = 0.0
    reb_season: float = 0.0
    minutes: float
    expected_minutes: float = 0
    usage: float
    usage_source: str = "Estimated"
    pace: float = 0
    opponent_defense: float = 0
    home_away_adjustment: float = 0
    trend: float = 0
    monte_carlo: int = 10000
    recent_std: float = 5
    reasons: List[str]
    thresholds: dict[str, float]
    factors: dict[str, float] = {}
    h2h: Optional[float] = None
    h2h_games: int = 0
    injury_status: str = ""
    injury_bump: float = 0.0
    rest_days: Optional[int] = None
    b2b: bool = False
    game_total: Optional[float] = None
    spread: Optional[float] = None
    context_pct: float = 0.0
    recent_games: list = []
    h2h_log: list = []
    pick_side: Optional[str] = None      # OVER/UNDER (strana s vecom prednoscu nad kladionicom)
    win_chance: Optional[float] = None   # vjerovatnoca da pick prodje (%, model, skupljen prema 50%)
    market_prob: Optional[float] = None  # trzisna vjerovatnoca iste strane bez vig-a (%)
    dtm: float = 0.0                     # Difference To Market = win_chance - market_prob (procentni poeni)
    odds_price: Optional[float] = None   # decimalna kvota te strane
    books: int = 0
    game_date: str = ""
    game_time: str = ""
    headshot: Optional[str] = None
    source: str = "ESPN"
    leader_score: float = 0.0
    is_leader: bool = False
    position_group: str = ""
    opponent_defense_pos: Optional[float] = None   # faktor odbrane protivnika za poziciju igraca (>1 = tezi)
    defense_pos_games: int = 0
    opponent_missing_defenders: list = []
