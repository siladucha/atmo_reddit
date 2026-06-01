from app.models.user import User
from app.models.user_role import UserRole
from app.models.client import Client
from app.models.avatar import Avatar
from app.models.avatar_pool import AvatarPool
from app.models.subreddit import ClientSubreddit, Subreddit, ClientSubredditAssignment
from app.models.thread import RedditThread
from app.models.comment_draft import CommentDraft
from app.models.post_draft import PostDraft
from app.models.hobby import HobbySubreddit
from app.models.ai_usage import AIUsageLog
from app.models.audit import AuditLog
from app.models.settings import SystemSetting
from app.models.activity_event import ActivityEvent
from app.models.scrape_log import ScrapeLog
from app.models.thread_score import ThreadScore
from app.models.subreddit_karma import SubredditKarma
from app.models.avatar_profile_snapshot import AvatarProfileSnapshot
from app.models.analysis_edit import AnalysisEditRecord
from app.models.avatar_subreddit_presence import AvatarSubredditPresence
from app.models.edit_record import EditRecord
from app.models.correction_pattern import CorrectionPattern
from app.models.avatar_rental import AvatarRental
from app.models.user_client_assignment import UserClientAssignment
from app.models.strategy_document import StrategyDocument
from app.models.epg_slot import EPGSlot
from app.models.reddit_app import RedditApp
from app.models.posting_event import PostingEvent

__all__ = [
    "User",
    "UserRole",
    "Client",
    "Avatar",
    "AvatarPool",
    "ClientSubreddit",
    "Subreddit",
    "ClientSubredditAssignment",
    "RedditThread",
    "CommentDraft",
    "PostDraft",
    "HobbySubreddit",
    "AIUsageLog",
    "AuditLog",
    "SystemSetting",
    "ActivityEvent",
    "ScrapeLog",
    "ThreadScore",
    "SubredditKarma",
    "AvatarProfileSnapshot",
    "AnalysisEditRecord",
    "AvatarSubredditPresence",
    "EditRecord",
    "CorrectionPattern",
    "AvatarRental",
    "UserClientAssignment",
    "StrategyDocument",
    "EPGSlot",
    "RedditApp",
    "PostingEvent",
]
