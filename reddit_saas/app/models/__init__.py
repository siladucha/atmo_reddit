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
from app.models.llm_quality_snapshot import LLMQualitySnapshot
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
from app.models.discovery_session import DiscoverySession
from app.models.discovery_entity import DiscoveryEntity
from app.models.discovery_hypothesis import DiscoveryHypothesis
from app.models.visibility_report import VisibilityReport
from app.models.opportunity import Opportunity
from app.models.decision_record import DecisionRecord
from app.models.zero_day_report import ZeroDayReport
from app.models.performance_metric import PerformanceMetric
from app.models.karma_snapshot import KarmaSnapshot
from app.models.client_action_log import ClientActionLog
from app.models.voice_feedback import VoiceFeedback
from app.models.subreddit_request import SubredditRequest
from app.models.subreddit_risk_profile import SubredditRiskProfile
from app.models.subreddit_daily_stats import SubredditDailyStats
from app.models.avatar_subreddit_ban import AvatarSubredditBan

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
    "DiscoverySession",
    "DiscoveryEntity",
    "DiscoveryHypothesis",
    "VisibilityReport",
    "Opportunity",
    "DecisionRecord",
    "ZeroDayReport",
    "PerformanceMetric",
    "KarmaSnapshot",
    "ClientActionLog",
    "VoiceFeedback",
    "SubredditRequest",
    "SubredditRiskProfile",
    "SubredditDailyStats",
    "AvatarSubredditBan",
    "ExecutionTask",
    "DeliveryAttempt",
    "GeoPrompt",
    "GeoCompetitor",
    "GeoExecutionBatch",
    "GeoQueryResult",
    "GeoFrequencyMetric",
    "AvatarDraft",
    "TrialSignal",
    "TrialScore",
    "TrialFailure",
    "TrialSalesSummary",
    "TrialIntelligenceEvent",
    "AuditRun",
    "AuditFinding",
    "LLMTaskRecord",
    "ReviewSnapshot",
    "DailyReviewSession",
    "ReviewDecision",
    "IntelligenceReport",
    "ExecutionNode",
    "ClientIntelligenceReport",
    "ForecastAccuracyLog",
    "ObservedSnapshot",
    "ExperimentRun",
    "TreatmentGroup",
    "AvatarAssignment",
    "MetricSnapshot",
    "WeeklyReport",
    "ControlViolation",
]

# GEO/AEO Prompt Monitoring
from app.models.geo_prompt import GeoPrompt
from app.models.geo_competitor import GeoCompetitor
from app.models.geo_execution import GeoExecutionBatch, GeoQueryResult, GeoFrequencyMetric
from app.models.notification import Notification

# Execution Task Delivery
from app.models.execution_task import ExecutionTask, DeliveryAttempt

# BYOA Avatar Provisioning
from app.models.avatar_draft import AvatarDraft

# Trial Conversion Intelligence
from app.models.trial_signal import TrialSignal
from app.models.trial_score import TrialScore
from app.models.trial_failure import TrialFailure
from app.models.trial_sales_summary import TrialSalesSummary
from app.models.trial_intelligence_event import TrialIntelligenceEvent

# Production Readiness Audit
from app.models.audit_finding import AuditRun, AuditFinding, LLMTaskRecord

# Daily Operations Review
from app.models.review_snapshot import ReviewSnapshot
from app.models.daily_review_session import DailyReviewSession
from app.models.review_decision import ReviewDecision
from app.models.intelligence_report import IntelligenceReport

# Pipeline Observability
from app.models.pipeline_run import PipelineRun

# Browser Extension
from app.models.execution_node import ExecutionNode

# Forecast & Reporting Layer
from app.models.intelligence_report import ClientIntelligenceReport
from app.models.forecast_accuracy import ForecastAccuracyLog
from app.models.observed_snapshot import ObservedSnapshot

# A/B Test Framework
from app.models.ab_test import (
    ExperimentRun,
    TreatmentGroup,
    AvatarAssignment,
    MetricSnapshot,
    WeeklyReport,
    ControlViolation,
)

# Billing Plan Enforcement
from app.models.plan_definition import PlanDefinition
from app.models.client_subscription import ClientSubscription
from app.models.webhook_event import WebhookEvent
from app.models.billing_period_history import BillingPeriodHistory
from app.models.upsell_event import UpsellEvent
