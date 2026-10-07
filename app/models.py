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
    game_date: str = ""
    game_time: str = ""
    headshot: Optional[str] = None
    source: str = "ESPN"
    leader_score: float = 0.0
    is_leader: bool = False
