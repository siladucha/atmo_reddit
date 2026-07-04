# Extension Posting A/B Test — Design

## System Architecture (High-Level)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     EXPERIMENT FRAMEWORK                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐   │
│  │ Experiment   │   │ Control Var  │   │ Posting Method       │   │
│  │ Manager      │   │ Enforcer     │   │ Router               │   │
│  │ (lifecycle)  │   │ (gates)      │   │ (channel override)   │   │
│  └──────┬───────┘   └──────┬───────┘   └──────────┬───────────┘   │
│         │                  │                       │               │
│         ▼                  ▼                       ▼               │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    EPG Pipeline Integration                   │  │
│  │  (budget override → subreddit filter → content type gate)    │  │
│  └──────────────────────────────────────────────┬───────────────┘  │
│                                                 │                  │
└─────────────────────────────────────────────────┼──────────────────┘
                                                  │
              ┌───────────────────────────────────┼───────────────┐
              │                                   │               │
     ┌────────▼──────┐  ┌────────────▼──────┐  ┌─▼────────────┐
     │ old_reddit    │  │ manual_email      │  │ new_reddit   │
     │ (textarea +   │  │ (standard email   │  │ (debugger    │
     │  .save btn)   │  │  task delivery)   │  │  trusted     │
     │               │  │                   │  │  clicks)     │
     └───────┬───────┘  └────────┬──────────┘  └──────┬───────┘
             │                   │                     │
             └───────────────────┼─────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Metric Collector       │
                    │  (weekly snapshot,      │
                    │   immutable records)    │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  Statistical Reporter   │
                    │  (chi-sq, Mann-Whitney, │
                    │   effect size, p-value) │
                    └─────────────────────────┘
```


---

## Data Schema

### New Table: `ab_experiments`

```sql
CREATE TABLE ab_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    hypothesis TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
        -- draft | active | paused | concluded | aborted

    -- Configuration
    planned_duration_weeks INT NOT NULL DEFAULT 8,
    daily_volume_per_avatar INT NOT NULL DEFAULT 3,
    subreddit_risk_max INT NOT NULL DEFAULT 40,
    content_type VARCHAR(20) NOT NULL DEFAULT 'hobby',
        -- hobby | phase1 (restricts generation to safe content)
    generation_model VARCHAR(100) NOT NULL,
        -- locked LLM model for all groups

    -- Lifecycle timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    paused_at TIMESTAMPTZ,
    resumed_at TIMESTAMPTZ,
    concluded_at TIMESTAMPTZ,
    pause_reason TEXT,

    -- Metadata
    created_by UUID REFERENCES users(id),
    conclusion_summary JSONB,
        -- final stats, h0 determination, recommendations
    config_history JSONB NOT NULL DEFAULT '[]'
        -- append-only log of config changes
);

CREATE INDEX ix_ab_experiments_status ON ab_experiments(status);
```


### New Table: `ab_treatment_groups`

```sql
CREATE TABLE ab_treatment_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    posting_method VARCHAR(30) NOT NULL,
        -- old_reddit | manual_email | new_reddit_debugger
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_ab_group_experiment_method
        UNIQUE (experiment_id, posting_method)
);

CREATE INDEX ix_ab_groups_experiment ON ab_treatment_groups(experiment_id);
```

### New Table: `ab_avatar_assignments`

```sql
CREATE TABLE ab_avatar_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES ab_treatment_groups(id) ON DELETE CASCADE,
    avatar_id UUID NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Eligibility snapshot at assignment time (immutable)
    assignment_snapshot JSONB NOT NULL,
        -- {account_age_days, cqs_level, karma_comment, warming_phase, health_status}

    -- Exclusion tracking
    is_excluded BOOLEAN NOT NULL DEFAULT false,
    excluded_at TIMESTAMPTZ,
    exclusion_reason VARCHAR(100),
        -- suspended | deactivated | shadowbanned | operator_removed

    CONSTRAINT uq_ab_avatar_experiment
        UNIQUE (experiment_id, avatar_id)
);

CREATE INDEX ix_ab_assignments_experiment ON ab_avatar_assignments(experiment_id);
CREATE INDEX ix_ab_assignments_avatar ON ab_avatar_assignments(avatar_id);
CREATE INDEX ix_ab_assignments_group ON ab_avatar_assignments(group_id);
```


### New Table: `ab_metric_snapshots`

```sql
CREATE TABLE ab_metric_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    avatar_id UUID NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    group_id UUID NOT NULL REFERENCES ab_treatment_groups(id) ON DELETE CASCADE,
    week_number INT NOT NULL,
        -- 1-based week within experiment
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Health metrics (immutable once written)
    removal_rate NUMERIC(5,4),
        -- deleted / total_posted (0.0000 - 1.0000)
    total_posted INT NOT NULL DEFAULT 0,
    total_deleted INT NOT NULL DEFAULT 0,

    karma_velocity_4h NUMERIC(8,2),
        -- avg karma at 4h snapshot
    karma_velocity_24h NUMERIC(8,2),
    karma_velocity_7d NUMERIC(8,2),

    shadowban_events INT NOT NULL DEFAULT 0,
        -- count of is_shadowbanned transitions false→true

    cqs_level_start VARCHAR(20),
    cqs_level_end VARCHAR(20),
    cqs_changed BOOLEAN NOT NULL DEFAULT false,

    subreddit_bans_new INT NOT NULL DEFAULT 0,
        -- new AvatarSubredditBan records this week

    phase_at_start INT NOT NULL,
    phase_at_end INT NOT NULL,
    phase_promoted BOOLEAN NOT NULL DEFAULT false,

    account_warnings INT NOT NULL DEFAULT 0,

    -- Control variable compliance
    volume_violations INT NOT NULL DEFAULT 0,
        -- days where avatar exceeded daily_volume
    subreddit_violations INT NOT NULL DEFAULT 0,
        -- posts in subs with risk > max

    -- Task execution metrics (method-specific)
    tasks_attempted INT NOT NULL DEFAULT 0,
    tasks_succeeded INT NOT NULL DEFAULT 0,
    tasks_failed INT NOT NULL DEFAULT 0,
    failure_reasons JSONB DEFAULT '{}',
        -- {"DOM_CHANGED": 2, "TIMEOUT": 1, ...}

    CONSTRAINT uq_ab_metric_avatar_week
        UNIQUE (experiment_id, avatar_id, week_number)
);

CREATE INDEX ix_ab_metrics_experiment_week
    ON ab_metric_snapshots(experiment_id, week_number);
CREATE INDEX ix_ab_metrics_group_week
    ON ab_metric_snapshots(group_id, week_number);
```


### New Table: `ab_weekly_reports`

```sql
CREATE TABLE ab_weekly_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    week_number INT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Statistical results per metric
    statistics_json JSONB NOT NULL,
        -- Structure:
        -- {
        --   "removal_rate": {
        --     "groups": {"old_reddit": {"mean": 0.05, "median": 0.04, "n": 6}, ...},
        --     "comparisons": [
        --       {"pair": ["old_reddit", "manual_email"], "test": "mann_whitney_u",
        --        "statistic": 12.5, "p_value": 0.34, "effect_size": 0.12,
        --        "significant": false}
        --     ]
        --   },
        --   "shadowban_events": {
        --     "groups": {"old_reddit": {"count": 0, "n": 6}, ...},
        --     "comparisons": [
        --       {"pair": ["old_reddit", "manual_email"], "test": "chi_squared",
        --        "statistic": 0.5, "p_value": 0.78, "significant": false}
        --     ]
        --   }
        -- }

    -- Cumulative analysis (all weeks up to this point)
    cumulative_json JSONB NOT NULL,

    -- Raw data for transparency
    raw_data_json JSONB NOT NULL,
        -- per-avatar values for audit

    -- Alert flags
    early_termination_recommended BOOLEAN NOT NULL DEFAULT false,
    alert_metrics JSONB DEFAULT '[]',
        -- metrics with p<0.05 for 2+ consecutive weeks

    CONSTRAINT uq_ab_report_experiment_week
        UNIQUE (experiment_id, week_number)
);
```

### New Table: `ab_control_violations`

```sql
CREATE TABLE ab_control_violations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    avatar_id UUID NOT NULL REFERENCES avatars(id),
    violation_type VARCHAR(50) NOT NULL,
        -- volume_exceeded | subreddit_risk_exceeded | content_type_violation
    violation_date DATE NOT NULL,
    details JSONB NOT NULL,
        -- {"expected": 3, "actual": 4, "subreddit": "r/sysadmin", "risk_score": 65}
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_ab_violations_experiment
    ON ab_control_violations(experiment_id, violation_date);
```


### New Table: `ab_audit_log`

```sql
CREATE TABLE ab_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES ab_experiments(id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,
        -- created | started | paused | resumed | concluded | aborted
        -- avatar_assigned | avatar_excluded | config_changed
        -- violation_logged | report_generated | alert_emitted
    actor_id UUID REFERENCES users(id),
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_ab_audit_experiment ON ab_audit_log(experiment_id, created_at);
```

---

## Service Architecture

### 1. ExperimentManager (`app/services/ab_test/experiment_manager.py`)

Handles experiment lifecycle: create, start, pause, resume, conclude, abort.

```python
class ExperimentManager:
    """Manages A/B test experiment lifecycle."""

    def create_experiment(
        self, db: Session, name: str, hypothesis: str,
        duration_weeks: int, groups: list[dict],
        daily_volume: int = 3, risk_max: int = 40,
        content_type: str = "hobby", model: str = None,
    ) -> ABExperiment:
        """Create experiment in draft state.

        Validates:
        - At least 2 groups with distinct posting methods
        - Model string is valid (exists in settings or MODEL_COSTS)
        - Duration 4-16 weeks
        """
        ...

    def start_experiment(self, db: Session, experiment_id: UUID) -> ABExperiment:
        """Transition draft → active.

        Validates:
        - Each group has ≥5 non-excluded avatars
        - All avatars meet eligibility (CQS ≠ lowest, not frozen)
        - Records started_at, emits activity_event
        """
        ...

    def pause_experiment(self, db: Session, experiment_id: UUID, reason: str) -> ABExperiment:
        """Transition active → paused. Suspends enforcement + overrides."""
        ...

    def resume_experiment(self, db: Session, experiment_id: UUID) -> ABExperiment:
        """Transition paused → active. Re-applies enforcement."""
        ...

    def conclude_experiment(self, db: Session, experiment_id: UUID) -> ABExperiment:
        """Transition active → concluded. Generates final report."""
        ...

    def abort_experiment(self, db: Session, experiment_id: UUID, reason: str) -> ABExperiment:
        """Transition any → aborted. Emergency stop."""
        ...
```


### 2. GroupAssigner (`app/services/ab_test/group_assigner.py`)

Handles avatar-to-group assignment with eligibility validation.

```python
class GroupAssigner:
    """Assigns avatars to treatment groups with eligibility checks."""

    ELIGIBILITY_CRITERIA = {
        "cqs_not_lowest": lambda a: a.cqs_level != "lowest",
        "not_frozen": lambda a: not a.is_frozen,
        "not_shadowbanned": lambda a: not a.is_shadowbanned,
        "active": lambda a: a.active,
        "has_account_age": lambda a: a.reddit_account_created is not None,
    }

    def get_eligible_avatars(
        self, db: Session, experiment_id: UUID
    ) -> list[dict]:
        """Return avatars that meet all eligibility criteria.

        Returns list of {avatar, eligible: bool, reasons: [str]}
        """
        ...

    def assign_avatar(
        self, db: Session, experiment_id: UUID,
        group_id: UUID, avatar_id: UUID,
    ) -> ABAssignment:
        """Assign avatar to group.

        Validates:
        - Avatar not already assigned in this experiment
        - Avatar meets eligibility criteria
        - Account age within ±2 weeks of group median
        - Stores immutable snapshot of avatar state at assignment
        """
        ...

    def exclude_avatar(
        self, db: Session, experiment_id: UUID,
        avatar_id: UUID, reason: str,
    ) -> ABAssignment:
        """Mark avatar as excluded from analysis."""
        ...

    def check_ongoing_eligibility(
        self, db: Session, experiment_id: UUID
    ) -> list[dict]:
        """Check all assigned avatars for exclusion triggers.

        Called daily. Returns avatars that became ineligible.
        Triggers: suspended, deactivated, shadowbanned (persistent).
        """
        ...
```

### 3. ControlEnforcer (`app/services/ab_test/control_enforcer.py`)

Gates the EPG pipeline for experiment participants.

```python
class ControlEnforcer:
    """Enforces control variables for active experiments."""

    def get_experiment_config(
        self, db: Session, avatar_id: UUID
    ) -> ExperimentConfig | None:
        """If avatar is in an active experiment, return its constraints.

        Returns None if avatar is not in any active experiment.
        Called by EPG pipeline before slot creation.
        """
        ...

    def check_daily_volume(
        self, db: Session, avatar_id: UUID, experiment_id: UUID
    ) -> int:
        """Return remaining budget for today (daily_volume - already_posted).

        If already at limit, returns 0 (EPG should not create more slots).
        """
        ...

    def filter_subreddits(
        self, db: Session, experiment_id: UUID,
        candidates: list[str],
    ) -> list[str]:
        """Filter candidate subreddits to those within risk_max.

        Only allows subs with SubredditRiskProfile.risk_score <= config.risk_max.
        Subs without a profile are excluded (conservative).
        """
        ...

    def validate_content_type(
        self, experiment: ABExperiment, slot_type: str
    ) -> bool:
        """Check if content type matches experiment constraint.

        If experiment.content_type == 'hobby', only hobby slots allowed.
        """
        ...

    def log_violation(
        self, db: Session, experiment_id: UUID,
        avatar_id: UUID, violation_type: str, details: dict,
    ) -> None:
        """Record a control variable violation."""
        ...
```


### 4. PostingMethodRouter (`app/services/ab_test/method_router.py`)

Overrides delivery channel for experiment participants.

```python
class PostingMethodRouter:
    """Routes tasks to the correct posting method per experiment group."""

    METHOD_TO_CHANNEL = {
        "old_reddit": "extension",      # extension with old_reddit mode
        "manual_email": "email",        # standard email delivery
        "new_reddit_debugger": "extension",  # extension with debugger mode
    }

    def get_posting_config(
        self, db: Session, avatar_id: UUID
    ) -> PostingMethodConfig | None:
        """Get posting method override for experiment participant.

        Returns None if avatar is not in active experiment.
        Returns PostingMethodConfig with:
        - delivery_channel: email | extension
        - posting_mode: old_reddit | new_reddit_debugger | None
        - experiment_id: UUID (for task tagging)
        - group_id: UUID (for metric attribution)
        """
        ...

    def apply_to_task(
        self, task: ExecutionTask, config: PostingMethodConfig
    ) -> ExecutionTask:
        """Apply posting method override to an execution task.

        Sets:
        - task.delivery_channel = config.delivery_channel
        - task.metadata["experiment_id"] = config.experiment_id
        - task.metadata["group_id"] = config.group_id
        - task.metadata["posting_mode"] = config.posting_mode
        """
        ...


@dataclass
class PostingMethodConfig:
    delivery_channel: str       # "email" | "extension"
    posting_mode: str | None    # "old_reddit" | "new_reddit_debugger" | None
    experiment_id: UUID
    group_id: UUID
```

### 5. MetricCollector (`app/services/ab_test/metric_collector.py`)

Collects weekly health metrics per avatar from existing data sources.

```python
class MetricCollector:
    """Collects health metrics for experiment participants."""

    def collect_weekly_metrics(
        self, db: Session, experiment_id: UUID, week_number: int,
    ) -> list[ABMetricSnapshot]:
        """Collect all metrics for all active (non-excluded) avatars.

        Sources:
        - Removal rate: CommentDraft(status=posted, is_deleted) in date window
        - Karma velocity: KarmaSnapshot joined to drafts in date window
        - Shadowban events: ActivityEvent(type=global_shadowban_detected) in window
        - CQS changes: Avatar.cqs_level vs last week's snapshot
        - Subreddit bans: AvatarSubredditBan(created_at) in window
        - Phase progression: Avatar.warming_phase vs assignment snapshot
        - Account warnings: HealthCheckDetails for new restrictions
        - Task metrics: ExecutionTask + extension events in window
        - Control violations: ab_control_violations in window

        Returns immutable snapshot records.
        """
        ...

    def _compute_removal_rate(
        self, db: Session, avatar_id: UUID,
        week_start: date, week_end: date,
    ) -> tuple[float | None, int, int]:
        """(rate, total_posted, total_deleted)"""
        ...

    def _compute_karma_velocity(
        self, db: Session, avatar_id: UUID,
        week_start: date, week_end: date,
    ) -> tuple[float | None, float | None, float | None]:
        """(avg_4h, avg_24h, avg_7d) from KarmaSnapshot records."""
        ...

    def _count_shadowban_events(
        self, db: Session, avatar_id: UUID,
        week_start: datetime, week_end: datetime,
    ) -> int:
        ...

    def _count_subreddit_bans(
        self, db: Session, avatar_id: UUID,
        week_start: datetime, week_end: datetime,
    ) -> int:
        ...

    def _collect_task_metrics(
        self, db: Session, avatar_id: UUID,
        experiment_id: UUID,
        week_start: datetime, week_end: datetime,
    ) -> dict:
        """Count attempted/succeeded/failed + failure reason breakdown."""
        ...
```


### 6. StatisticalReporter (`app/services/ab_test/statistical_reporter.py`)

Performs hypothesis testing and generates weekly reports.

```python
from scipy import stats

class StatisticalReporter:
    """Generates statistical reports comparing treatment groups."""

    # Significance threshold
    ALPHA = 0.05
    # Consecutive weeks for early termination alert
    CONSECUTIVE_WEEKS_ALERT = 2

    def generate_weekly_report(
        self, db: Session, experiment_id: UUID, week_number: int,
    ) -> ABWeeklyReport:
        """Generate full statistical report for a given week.

        Steps:
        1. Load metric snapshots for this week (per group)
        2. Compute per-group aggregates (mean, median, n)
        3. Run pairwise comparisons (chi-sq or Mann-Whitney U)
        4. Compute cumulative stats (all weeks so far)
        5. Check early termination criteria
        6. Store immutable report record
        """
        ...

    def _compare_continuous(
        self, group_a_values: list[float], group_b_values: list[float],
        metric_name: str,
    ) -> ComparisonResult:
        """Mann-Whitney U for continuous metrics (removal_rate, karma).

        Returns ComparisonResult with statistic, p_value, effect_size (r),
        and significant flag.
        """
        u_stat, p_value = stats.mannwhitneyu(
            group_a_values, group_b_values,
            alternative="two-sided"
        )
        n = len(group_a_values) + len(group_b_values)
        effect_size = abs(u_stat - (len(group_a_values) * len(group_b_values) / 2)) / (
            len(group_a_values) * len(group_b_values) / 2
        ) if n > 0 else 0
        return ComparisonResult(
            test="mann_whitney_u",
            statistic=u_stat,
            p_value=p_value,
            effect_size=effect_size,
            significant=p_value < self.ALPHA,
        )

    def _compare_categorical(
        self, group_a_counts: tuple[int, int],
        group_b_counts: tuple[int, int],
        metric_name: str,
    ) -> ComparisonResult:
        """Chi-squared for categorical metrics (shadowban yes/no, CQS change).

        Input: (events, non_events) per group.
        """
        contingency = [list(group_a_counts), list(group_b_counts)]
        chi2, p_value, dof, expected = stats.chi2_contingency(contingency)
        n = sum(group_a_counts) + sum(group_b_counts)
        cramers_v = (chi2 / n) ** 0.5 if n > 0 else 0
        return ComparisonResult(
            test="chi_squared",
            statistic=chi2,
            p_value=p_value,
            effect_size=cramers_v,
            significant=p_value < self.ALPHA,
        )

    def _check_early_termination(
        self, db: Session, experiment_id: UUID, week_number: int,
    ) -> tuple[bool, list[str]]:
        """Check if primary metrics show significance for 2+ weeks.

        Primary metrics: removal_rate, shadowban_events.
        Returns (recommend_termination, alert_metrics).
        """
        ...

    def generate_final_report(
        self, db: Session, experiment_id: UUID,
    ) -> dict:
        """Generate conclusion summary with H0 determination.

        Returns:
        {
            "h0_rejected": bool,
            "primary_metrics_significant": [...],
            "confidence_intervals": {...},
            "recommendation": str,
            "total_weeks": int,
            "total_avatars_analyzed": int,
            "exclusions": int,
        }
        """
        ...


@dataclass
class ComparisonResult:
    test: str               # "mann_whitney_u" | "chi_squared"
    statistic: float
    p_value: float
    effect_size: float      # r (Mann-Whitney) or Cramér's V (chi-sq)
    significant: bool       # p < ALPHA
```


---

## Pipeline Integration Points

### EPG Budget Override

In `app/services/portfolio_manager.py` → `build_portfolio()`:

```python
# BEFORE existing budget calculation:
from app.services.ab_test.control_enforcer import ControlEnforcer

enforcer = ControlEnforcer()
experiment_config = enforcer.get_experiment_config(db, avatar_id)

if experiment_config:
    # Override budget to experiment daily_volume
    remaining = enforcer.check_daily_volume(db, avatar_id, experiment_config.experiment_id)
    max_comments = remaining
    # Skip if already at daily limit
    if remaining <= 0:
        return "experiment_budget_exhausted"
```

### Subreddit Filtering

In `app/services/opportunity_engine.py` → `scan_opportunities()`:

```python
# AFTER candidate subreddits collected:
if experiment_config:
    candidates = enforcer.filter_subreddits(db, experiment_config.experiment_id, candidates)
```

### Task Routing Override

In `app/services/execution_tasks.py` → `create_execution_task()`:

```python
# AFTER task created, BEFORE commit:
from app.services.ab_test.method_router import PostingMethodRouter

router = PostingMethodRouter()
posting_config = router.get_posting_config(db, slot.avatar_id)
if posting_config:
    task = router.apply_to_task(task, posting_config)
```

### Extension Posting Mode

In `ramp_extension/background.js` → task execution:

```javascript
// When task has metadata.posting_mode:
async function executeTask(task) {
    const mode = task.metadata?.posting_mode || "new_reddit_debugger";

    if (mode === "old_reddit") {
        // Navigate to old.reddit.com version of thread
        const oldUrl = task.thread_url.replace("www.reddit.com", "old.reddit.com")
                                       .replace("reddit.com", "old.reddit.com");
        await navigateToUrl(oldUrl);
        await oldRedditPost(task.text);
    } else {
        // Default: new reddit with chrome.debugger
        await navigateToUrl(task.thread_url);
        await newRedditDebuggerPost(task.text);
    }
}

async function oldRedditPost(text) {
    // 1. Find comment textarea: document.querySelector("textarea[name='text']")
    //    OR .usertext-edit textarea
    // 2. Set value directly (no shadow DOM, no trusted click needed)
    // 3. Click .save button (standard DOM, no chrome.debugger needed)
    // 4. Verify comment appeared in DOM
    await sendContentMessage("OLD_REDDIT_POST", { text });
}
```

### Phase Evaluator Block

In `app/services/phase.py` → `evaluate_avatar_phase()`:

```python
# At start of evaluation:
from app.services.ab_test.control_enforcer import ControlEnforcer

enforcer = ControlEnforcer()
if enforcer.get_experiment_config(db, avatar_id):
    # Block phase changes during active experiment
    logger.info("Phase eval skipped for avatar %s (in active A/B test)", avatar_id)
    return None  # no change
```

---

## Old Reddit Posting — Content Script Addition

### New Handler: `OLD_REDDIT_POST`

```javascript
// ramp_extension/content/old-reddit-actions.js

function handleOldRedditPost(payload) {
    const { text } = payload;

    // Old reddit comment form detection
    // Two modes: (a) already on thread with comment box, (b) need to expand
    const textarea = document.querySelector(
        ".usertext-edit textarea, " +
        "#comment_reply_form textarea, " +
        "textarea[name='text']"
    );

    if (!textarea) {
        // Try to expand the reply form
        const replyBtn = document.querySelector("a.reply-button, .reply-button a");
        if (replyBtn) {
            replyBtn.click();
            // Wait for textarea to appear
            return waitForElement("textarea[name='text']", 3000)
                .then(ta => insertAndSubmitOldReddit(ta, text));
        }
        return { success: false, error: "NO_TEXTAREA_FOUND" };
    }

    return insertAndSubmitOldReddit(textarea, text);
}

function insertAndSubmitOldReddit(textarea, text) {
    // Old reddit uses plain textarea — no shadow DOM, no Lexical
    textarea.focus();
    textarea.value = text;
    // Trigger input event for any listeners
    textarea.dispatchEvent(new Event("input", { bubbles: true }));

    // Find save button (sibling or nearby .save)
    const form = textarea.closest("form") || textarea.closest(".usertext-edit");
    const saveBtn = form?.querySelector("button[type='submit'], .save");

    if (!saveBtn) {
        return { success: false, error: "NO_SAVE_BUTTON" };
    }

    saveBtn.click();

    // Verify: wait for new comment to appear in DOM
    return waitForNewComment(text, 5000).then(found => ({
        success: found,
        error: found ? null : "COMMENT_NOT_VERIFIED",
    }));
}
```


---

## Celery Task: Weekly Metric Collection & Reporting

### New Task: `collect_ab_test_metrics`

```python
# app/tasks/ab_test.py

@shared_task(name="collect_ab_test_metrics", queue="celery")
def collect_ab_test_metrics():
    """Weekly metric collection + report generation for active experiments.

    Schedule: Sunday 06:00 (after phase evaluation, before pipeline).
    """
    with get_db_session() as db:
        active_experiments = (
            db.query(ABExperiment)
            .filter(ABExperiment.status == "active")
            .all()
        )

        for experiment in active_experiments:
            # Determine current week number
            week_number = compute_week_number(experiment.started_at)

            # Skip if already collected this week
            existing = db.query(ABMetricSnapshot).filter(
                ABMetricSnapshot.experiment_id == experiment.id,
                ABMetricSnapshot.week_number == week_number,
            ).first()
            if existing:
                continue

            # Collect metrics
            collector = MetricCollector()
            snapshots = collector.collect_weekly_metrics(db, experiment.id, week_number)

            # Generate report
            reporter = StatisticalReporter()
            report = reporter.generate_weekly_report(db, experiment.id, week_number)

            # Check eligibility (ongoing)
            assigner = GroupAssigner()
            ineligible = assigner.check_ongoing_eligibility(db, experiment.id)
            for item in ineligible:
                assigner.exclude_avatar(db, experiment.id, item["avatar_id"], item["reason"])

            # Check experiment duration
            if week_number >= experiment.planned_duration_weeks:
                emit_activity_event(
                    db, event_type="ab_test_ready_for_conclusion",
                    details={"experiment_id": str(experiment.id), "week": week_number}
                )

            # Early termination check
            if report.early_termination_recommended:
                emit_activity_event(
                    db, event_type="ab_test_early_termination_recommended",
                    details={
                        "experiment_id": str(experiment.id),
                        "alert_metrics": report.alert_metrics,
                        "week": week_number,
                    }
                )
```

### Beat Schedule Entry

```python
# In app/tasks/worker.py beat_schedule:
"collect-ab-test-metrics": {
    "task": "collect_ab_test_metrics",
    "schedule": crontab(hour=6, minute=0, day_of_week=0),  # Sunday 06:00
},
```

### Daily Eligibility Check

```python
@shared_task(name="check_ab_test_eligibility", queue="celery")
def check_ab_test_eligibility():
    """Daily check for avatar exclusions in active experiments.

    Schedule: daily 06:30 (after phase eval + zone eval).
    """
    with get_db_session() as db:
        active_experiments = (
            db.query(ABExperiment)
            .filter(ABExperiment.status == "active")
            .all()
        )
        for experiment in active_experiments:
            assigner = GroupAssigner()
            ineligible = assigner.check_ongoing_eligibility(db, experiment.id)
            for item in ineligible:
                assigner.exclude_avatar(db, experiment.id, item["avatar_id"], item["reason"])
```


---

## Admin UI Design

### Route: `/admin/ab-tests`

**List page** showing all experiments with:
- Name + status badge (color-coded: draft=gray, active=green, paused=yellow, concluded=blue, aborted=red)
- Group count + avatar count per group
- Duration (planned weeks + current week if active)
- Start date
- Actions: View | Start | Pause | Conclude (context-dependent)

### Route: `/admin/ab-tests/{id}`

**Detail page** with tabs:

#### Tab 1: Configuration
- Experiment name, hypothesis, status
- Control variables (daily volume, risk max, content type, model)
- State transition buttons with confirmation modals
- Config change history

#### Tab 2: Groups & Assignments
- Treatment groups table (name, method, avatar count)
- Per-group avatar list (username, assignment date, eligibility status)
- "Assign Avatars" panel:
  - Eligible avatars listed with checkboxes
  - Group selector dropdown
  - Bulk assign button
- Excluded avatars section (with reason + date)

#### Tab 3: Metrics Dashboard
- Weekly metric charts (one chart per metric, lines colored by group)
- Significance markers (★) on weeks where p < 0.05
- Effect size bars alongside p-values
- Current week cumulative summary cards
- Raw data table (expandable per avatar)

#### Tab 4: Reports
- List of generated weekly reports
- Per-report: view statistics_json rendered as comparison tables
- Final conclusion report (when concluded)

#### Tab 5: Audit Log
- Chronological list of all actions, state transitions, violations
- Filterable by action type

### HTMX Partials

```
templates/
  admin_ab_tests.html              # list page
  admin_ab_test_detail.html        # detail page (tab container)
  partials/
    ab_test_config.html            # Tab 1
    ab_test_groups.html            # Tab 2
    ab_test_metrics.html           # Tab 3 (lazy-loaded charts)
    ab_test_reports.html           # Tab 4
    ab_test_audit.html             # Tab 5
    ab_test_assign_panel.html      # eligible avatar assignment UI
    ab_test_metric_chart.html      # single metric chart partial
```


---

## State Machine

```
                    ┌──────────┐
                    │  draft   │
                    └────┬─────┘
                         │ start (validate ≥5/group)
                         ▼
              ┌─────► active ◄─────┐
              │      └──┬──┬──┘    │
              │         │  │       │
         resume│    pause│  │conclude
              │         │  │       │
              │         ▼  │       ▼
              │   ┌─────────┐  ┌──────────┐
              └───┤ paused  │  │concluded │
                  └─────────┘  └──────────┘

              From ANY state (except concluded):
                         │
                    abort │
                         ▼
                  ┌──────────┐
                  │ aborted  │
                  └──────────┘
```

**Transition effects:**

| Transition | Effect |
|-----------|--------|
| draft → active | Validate group sizes, record `started_at`, apply overrides |
| active → paused | Suspend override enforcement, record `paused_at` + reason |
| paused → active | Re-apply overrides, record `resumed_at` |
| active → concluded | Generate final report, remove overrides, restore avatar channels |
| * → aborted | Immediate stop, remove overrides, record reason |

---

## Integration with Existing Safety Systems

### What the Experiment Framework Overrides

| System | Normal Behavior | During Experiment |
|--------|----------------|-------------------|
| EPG budget | Phase-based (1/3/7/12) | Fixed `daily_volume` (default 3) |
| Subreddit selection | All assigned subs | Only subs with risk ≤ `risk_max` |
| Content type | Phase-dependent | Locked to experiment `content_type` |
| Delivery channel | Avatar `delivery_channel` field | Group `posting_method` |
| Phase evaluation | Daily promote/demote | **Blocked** (phase frozen during experiment) |
| Generation model | DB `llm_generation_model` | Locked to experiment `generation_model` |

### What the Experiment Framework Does NOT Override

| System | Reason |
|--------|--------|
| Health checks | Must continue — shadowban detection is a measured outcome |
| CQS checks | Must continue — CQS level is a measured outcome |
| Safety gates (posting_safety.py) | Never bypass safety — if safety blocks, task fails and is recorded |
| Kill switches | Global emergency controls always take precedence |
| Fitness gate | Still applied — enforces sub-specific rules |
| Content safety (brand mentions) | Never bypass — would invalidate control variables |
| Quiet hours gate | Applied — but consistent across all groups |

### Conflict Resolution

If experiment override conflicts with a higher-priority system:

1. **Kill switch ON** → experiment paused automatically, event emitted
2. **Avatar frozen** → avatar excluded from experiment (exclusion reason: `frozen`)
3. **Avatar shadowbanned** → NOT excluded (this is a measurable outcome!), but if persistent >2 weeks → exclude
4. **Safety gate blocks** → task recorded as `failed`, counts toward `tasks_failed`

---

## Dependency: `scipy` Addition

The statistical reporting requires `scipy` for hypothesis testing:

```toml
# pyproject.toml addition:
[project.dependencies]
scipy = ">=1.11.0"
```

`scipy.stats.mannwhitneyu` and `scipy.stats.chi2_contingency` are the only functions used. No ML frameworks required.


---

## File Structure

```
app/
├── models/
│   └── ab_test.py                    # ABExperiment, ABTreatmentGroup, ABAssignment,
│                                     # ABMetricSnapshot, ABWeeklyReport,
│                                     # ABControlViolation, ABAuditLog
├── services/
│   └── ab_test/
│       ├── __init__.py
│       ├── experiment_manager.py     # Lifecycle management
│       ├── group_assigner.py         # Avatar assignment + eligibility
│       ├── control_enforcer.py       # Pipeline gates
│       ├── method_router.py          # Posting method override
│       ├── metric_collector.py       # Weekly metric collection
│       └── statistical_reporter.py   # Hypothesis testing + reports
├── tasks/
│   └── ab_test.py                    # collect_ab_test_metrics,
│                                     # check_ab_test_eligibility
├── routes/
│   └── admin_ab_test.py              # Admin UI routes (CRUD + actions)
├── templates/
│   ├── admin_ab_tests.html           # List page
│   ├── admin_ab_test_detail.html     # Detail page
│   └── partials/
│       ├── ab_test_config.html
│       ├── ab_test_groups.html
│       ├── ab_test_metrics.html
│       ├── ab_test_reports.html
│       ├── ab_test_audit.html
│       ├── ab_test_assign_panel.html
│       └── ab_test_metric_chart.html
alembic/
└── versions/
    └── abt01_ab_test_framework.py    # All 6 tables in single migration

ramp_extension/
├── content/
│   └── old-reddit-actions.js         # Old reddit posting handlers
└── background.js                     # posting_mode routing logic
```

---

## Migration: `abt01`

Single migration creates all 6 tables. No FK dependencies on existing tables beyond
`avatars.id`, `users.id`, and `clients.id` (all exist).

Dependencies: none (standalone migration head, or depends on latest).

---

## Key Design Decisions

### 1. Why immutable metric snapshots (not computed on-demand)?

Historical metrics from Reddit can change (comments deleted later, karma fluctuates).
Snapshotting weekly ensures each week's report reflects data AS OF collection time.
Re-running statistics against the same week always yields identical results.

### 2. Why block phase evaluation during experiment?

Phase changes alter content type eligibility and daily budget — both are control variables.
If one group's avatars get promoted faster (random chance), it would introduce a confound.
Phase at start is recorded; days-to-promotion is tracked as an OUTCOME metric instead.

### 3. Why not auto-rebalance groups on exclusion?

Adding new avatars mid-experiment introduces temporal confounds (new avatars have
different exposure histories). Better to start with sufficient group sizes (≥5, target 7-8)
and accept some attrition. If a group drops below 4, alert for potential conclusion.

### 4. Why require manual start (not auto-start on creation)?

Operator needs time to verify assignments, check avatar health, ensure extension is
properly configured for old_reddit mode, and coordinate with executor. Draft state
allows setup without clock ticking.

### 5. Why only 2 statistical tests?

Mann-Whitney U (non-parametric, rank-based) handles small samples well without normality
assumptions. Chi-squared works for categorical outcomes. With n=5-10 per group,
parametric tests (t-test) have insufficient power. These two tests cover all metric types
in the requirements.

### 6. Why no fallback on posting method failure?

The experiment MUST isolate posting method. If old_reddit fails and falls back to email,
we lose the signal. Failed tasks are recorded and included in the reporting as a
method-specific reliability metric. This IS part of what we're testing.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Insufficient sample size (n<5 per group) | Cannot reach statistical significance | Minimum group size enforced at start. Target 7-8 per group to survive 1-2 exclusions. |
| Old reddit DOM changes during experiment | old_reddit group gets high task_failed rate | Monitor `failure_reasons` in weekly report. Alert if >30% failure rate. Can abort experiment. |
| Reddit batch action (mass shadowban) | Multiple groups affected simultaneously | This IS a measurable outcome. If it hits one group disproportionately, that's the signal. If all groups hit equally, it's noise (controlled for). |
| Control variable leakage (manual posting outside system) | Unmeasured activity confounds results | Executor instructions: ONLY post via system during experiment. Draft reconciliation can detect extra posts → flag as violation. |
| Experiment too short for rare events (shadowban) | 8 weeks may not produce enough events | Extend to 12 weeks if week-8 shows trends but no significance. Or accept "no detectable difference" as valid H0 result. |
| scipy package size in Docker image | Increased build time + image size (~30MB) | Acceptable tradeoff. scipy is well-maintained, BSD licensed, no transitive security issues. |
