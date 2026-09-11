# Strategy configuration

# A zone must be entered for the first-entry alert.
# While still inside, a status alert is sent at this interval.
ENTRY_ALERT_COOLDOWN_HOURS = 24
INSIDE_ALERT_HOURS = 24

# FVG smaller than this is ignored (absolute price points).
MIN_FVG_POINTS = 0.0

# Simple displacement filter:
# candle body must be at least this many ATRs.
MIN_DISPLACEMENT_BODY_ATR = 1.0

# Only scan zones formed by CLOSED monthly / 3-month candles.
USE_CLOSED_HTF_CANDLES_ONLY = True

# How many years of daily data to request.
HISTORY_PERIOD = "10y"
