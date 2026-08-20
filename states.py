from enum import Enum, auto


class AppState(Enum):
    WAIT_PHONE       = auto()
    WAIT_CODE        = auto()
    WAIT_PASSWORD    = auto()
    MAIN_MENU        = auto()
    SELECT_ENTITY    = auto()
    CONFIRM_ENTITY   = auto()
    DOWNLOADING      = auto()
    NFT_SCAN         = auto()
