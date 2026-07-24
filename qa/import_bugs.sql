DELETE FROM bug_reports;
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-001', 'Platform terminology Compliance Issue: "Avatar" terminology present in client portal UI', 'Description: Platform terminology Compliance Issue: "Avatar" terminology present in client portal UI
Pre-conditions: User is logged into the client portal / platform.
Steps: 1. Navigate through the client portal UI. 2. Observe terminology used across settings, onboarding, and review queues.
Expected: zero instances of "avatar" visible in client-facing UI. Every place a client sees text, it says "voice/voices" instead.', 'UX', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-002', 'Comment Regeneration Error: Failed attempt to regenerate comments triggers an error in client portal', 'Description: Comment Regeneration Error: Failed attempt to regenerate comments triggers an error in client portal
Pre-conditions: User is on the client portal reviewing comment queue.
Steps: 1. Locate a generated comment in the queue. 2. Click on the "Regenerate" button.
Expected: System successfully regenerates the comment draft without throwing UI errors.', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-003', 'Partial Comment Generation: System produces incomplete/partial comments for 2-3 days', 'Description: Partial Comment Generation: System produces incomplete/partial comments for 2-3 days
Pre-conditions: Automated comment generation pipeline runs.
Steps: 1. Trigger or wait for scheduled comment generation pipeline. 2. Check generated comment outputs in the review queue.
Expected: Comments are fully generated according to configured AI prompt rules.', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-004', 'Subreddit Limitations: Partner/Admin view restricts adding hobby sub-reddits due to limit validation', 'Description: Subreddit Limitations: Partner/Admin view restricts adding hobby sub-reddits due to limit validation
Pre-conditions: User is logged into Partner/Admin view. Tzvi Test, loanbase.com, XM Cyber
Steps: 1. Navigate to client / avatar configuration (e.g. Tzvi Test). 2. Attempt to add hobby sub-reddits. 3. Observe limitation error.
Expected: System applies sub-reddit limitations only to business/professional sub-reddits, while allowing hobby sub-reddits without restriction.', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-005', 'Missing Settings Option: Client-side cannot add custom tracking keywords in "Settings"', 'Description: Missing Settings Option: Client-side cannot add custom tracking keywords in "Settings"
Pre-conditions: User is logged into client-side Settings page. Tzvi Test, loanbase.com, XM Cyber
Steps: 1. Navigate to Settings page. 2. Look for option to add/manage custom target keywords.
Expected: Settings page provides input field/interface allowing users to add custom keywords. I played with the free trial for loanbase.com and it still found only 3 keywords, 2 of them were relevant. There are plenty of other keywords worth tracking for them, and I want to add it from the client side.
Would it be possible to allow it?', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-006', 'URL Input Field Locks After Failed Analysis during Onboarding Step 1', 'Description: URL Input Field Locks After Failed Analysis during Onboarding Step 1
Pre-conditions: User is on Step 1 of Onboarding Wizard.
Steps: 1. Input an invalid URL or URL with a typo. 2. Click to analyze. 3. Observe scrape/analysis failure error. 4. Attempt to edit/correct the URL input field.
Expected: URL field remains editable on failure; button shows "Retry" so user can correct typos.', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-007', 'Strict "Minimum 3 Keywords" Blocker on Free Trial Onboarding', 'Description: Strict "Minimum 3 Keywords" Blocker on Free Trial Onboarding
Pre-conditions: Free trial user analyzing a target domain returning fewer than 3 keywords (e.g., loanbase.com).
Steps: 1. Run website analysis returning 2 keywords. 2. Attempt to finalize free trial setup.
Expected: Onboarding completes successfully with a soft dashboard warning/recommendation instead of a blocking error. There are plenty of other keywords worth tracking for them, and I want to add it from the client side.', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-008', 'Session Expiration Redirects Free Trial User to Dashboard Instead of Wizard', 'Description: Session Expiration Redirects Free Trial User to Dashboard Instead of Wizard
Pre-conditions: Free trial user has incomplete onboarding wizard session that expires.
Steps: 1. Start onboarding wizard. 2. Allow session to expire or log out before completing. 3. Log back into the platform.
Expected: Unfinished trial users are redirected back to the onboarding wizard step.', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-009', 'Non-functional "Upgrade" Buttons across Trial Platform', 'Description: Non-functional "Upgrade" Buttons across Trial Platform
Pre-conditions: User is on free trial account.
Steps: 1. Click on any "Upgrade" button in UI.
Expected: System opens a pricing modal/popup with Stripe checkout links and a fallback "Contact Sales" option.', 'UX', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-010', 'Review Queue Hides Sub-reddit and Thread Titles for Inventory Profiles ("Unknown Thread")', 'Description: Review Queue Hides Sub-reddit and Thread Titles for Inventory Profiles ("Unknown Thread")
Pre-conditions: Partner view review queue with active inventory profiles (e.g., u/RunPriyaRun).
Steps: 1. Open review queue in Partner View. 2. Check thread title and sub-reddit headers for inventory profile drafts.
Expected: Specific thread title (e.g., "Tulips drooping :(") and sub-reddit (e.g., r/plantclinic) are displayed.', 'UX', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-011', 'Business Subreddit Comments Not Generating due to Empty Profile-level Config', 'Description: Business Subreddit Comments Not Generating due to Empty Profile-level Config
Pre-conditions: Phase 2 profile active with empty profile-level business_subreddits field.
Steps: 1. Trigger scheduled pipeline run. 2. Inspect comment generation logs for business subreddits.
Expected: System automatically inherits subreddits from client config when profile field is empty.', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-012', 'Critical failure when clicking "Mark as Posted" in Client Review page', 'Description: Critical failure when clicking "Mark as Posted" in Client Review page
Pre-conditions: User is on review page: https://gorampit.com/clients/721693db-cedc-4256-979d-823150894783/review
Steps: 1. Navigate to the review page. 2. Click "Mark as Posted" button on a comment item.
Expected: Comment status updates to Posted successfully without errors.', 'Backend', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-013', 'UI font size issue: Text is very small at standard 100% resolution', 'Description: UI font size issue: Text is very small at standard 100% resolution
Pre-conditions: Browser zoom level set to 100%.
Steps: 1. Open portal at 100% browser resolution. 2. Observe readable text scaling across pages.
Expected: Text is clearly legible with standard body font sizing (14px-16px).', 'UX', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-015', 'Recent activity display truncated: missing subreddit name (shows only "/r")', 'Description: Recent activity display truncated: missing subreddit name (shows only "/r")
Pre-conditions: User is viewing Avatar details page (e.g., "falky_finder").
Steps: 1. Open avatar attributes page. 2. Click avatar name "falky_finder". 3. Scroll to "Recent activity" section at bottom of page.
Expected: Full subreddit name is displayed (e.g. /r/cybersecurity) instead of truncated "/r".', 'UX', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-016', 'Chrome Extension error: "Account not recognized" upon connecting Reddit account tab', 'Description: Chrome Extension error: "Account not recognized" upon connecting Reddit account tab
Pre-conditions: Chrome extension installed and active.
Steps: 1. Open logged-in Reddit account tab. 2. Click "Connect" inside the extension.
Expected: Extension recognizes logged-in account and connects seamlessly.', 'Backend', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-017', 'Subreddits counter link opens 404 Error page in Client Manager account', 'Description: Subreddits counter link opens 404 Error page in Client Manager account
Pre-conditions: User logged into Client Manager account on Subreddits page.
Steps: 1. Click on "Subreddits" in menu. 2. Click on the count number next to a subreddit name.
Expected: System routes to the relevant threads/subreddits detail page.', 'Backend', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-018', 'Regenerating edited comment in Review Queue fails with "thread not found" popup', 'Description: Regenerating edited comment in Review Queue fails with "thread not found" popup
Pre-conditions: User is in Review Queue.
Steps: 1. Click "Review Queue" in right menu. 2. Make inline changes inside a comment text box. 3. Click "Regenerate".
Expected: Comment draft regenerates based on new edits without missing thread errors.', 'Backend', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-019', 'Outdated tooltip in Keywords section refers to non-existent Settings menu', 'Description: Outdated tooltip in Keywords section refers to non-existent Settings menu
Pre-conditions: User is viewing Keywords section.
Steps: 1. Hover over the "?" tooltip icon near the Keywords section title.
Expected: Tooltip provides accurate, up-to-date instructions reflecting current UI.', 'UX', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-020', 'Extension "Review" link in Pending Drafts opens an error page', 'Description: Extension "Review" link in Pending Drafts opens an error page
Pre-conditions: User connected via Chrome Extension with pending draft tasks.
Steps: 1. Open extension popup. 2. Click "Review" link on a PENDING DRAFTS task.
Expected: User redirected directly to correct Review Queue page in portal.', 'Backend', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-021', 'Extension zip load error "Manifest file is missing" due to nested extraction structure', 'Description: Extension zip load error "Manifest file is missing" due to nested extraction structure
Pre-conditions: Extension ZIP downloaded from client site.
Steps: 1. Unzip extension file. 2. Go to chrome://extensions -> Load unpacked. 3. Select outer unzipped folder.
Expected: Extension manifest loaded properly, or single-root ZIP provided to eliminate nested folder confusion.', 'UX', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-022', 'Deprecated extension static download page (index.html) still accessible', 'Description: Deprecated extension static download page (index.html) still accessible
Pre-conditions: User accesses https://gorampit.com/static/extension/index.html.
Steps: 1. Navigate to static extension index page.
Expected: Page is deleted or redirected to direct file download / active portal page.', 'UX', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-023', 'Portal missing thread availability view per subreddit based on RAMP restrictions', 'Description: Portal missing thread availability view per subreddit based on RAMP restrictions
Pre-conditions: User is in Client Manager portal viewing Subreddits.
Steps: 1. View Subreddits list in portal.
Expected: Portal displays available threads per subreddit filtered by RAMP restriction rules.', 'Backend', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-024', 'Missing explanatory tooltips/documentation for "Avatar Fitness" / "Avatar Fi"', 'Description: Missing explanatory tooltips/documentation for "Avatar Fitness" / "Avatar Fi"
Pre-conditions: User viewing Avatar Fitness metrics.
Steps: 1. Locate Avatar Fitness / Avatar Fi metric in UI.
Expected: UI displays tooltip, user guide explanation, or active account handle context.', 'UX', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-025', 'Global missing feature: No direct "Report Bug" link available across system layers', 'Description: Global missing feature: No direct "Report Bug" link available across system layers
Pre-conditions: User interacting with any layer of system (Portal, Extension, Admin).
Steps: 1. Check UI headers/footers/menus for feedback or bug reporting option.
Expected: Accessible "Report Bug" link present across all platform layers.', 'Backend', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-026', 'Extension links non-clickable; hides target subreddit and post context', 'Description: Extension links non-clickable; hides target subreddit and post context
Pre-conditions: User inspecting comment task inside Chrome Extension popup.
Steps: 1. View draft comment inside extension popup. 2. Attempt to click subreddit/post link.
Expected: Links are clickable, navigating directly to the destination subreddit or Reddit post.', 'UX', NULL, 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-027', 'Avatar Configuration Mismatch: System configured with legacy/shadowbanned accounts instead of active main accounts', 'Description: Avatar Configuration Mismatch: System configured with legacy/shadowbanned accounts instead of active main accounts
Pre-conditions: Client account configuration setup.
Steps: 1. Review active accounts assigned to client pipeline. 2. Check for legacy accounts (Middle-Mode3001, emma_richardson).
Expected: System replaces inactive/shadowbanned accounts with active target accounts (lucas_parker2, conor_lloyd, lena_gupta19).', 'Backend', 'High', 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-028', 'Onboarding Wizard Stalling for Client Account Setup (XM Cyber)', 'Description: Onboarding Wizard Stalling for Client Account Setup (XM Cyber)
Pre-conditions: User in onboarding wizard for client account (e.g., XM Cyber).
Steps: 1. Navigate to client onboarding wizard. 2. Run initial client setup steps.
Expected: Onboarding wizard completes all steps without freezing or getting stuck.', 'Backend', 'High', 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-029', 'Landscape Report Generation Failure: "Generate Report Now" throws UI alert without executing', 'Description: Landscape Report Generation Failure: "Generate Report Now" throws UI alert without executing
Pre-conditions: User attempting to generate a Landscape Report in the portal.
Steps: 1. Open Landscape Report generation view. 2. Click "Generate Report Now". 3. Check UI response and backend execution logs.
Expected: System initiates report generation, logs process execution, tracks AI token costs, and outputs complete report.', 'Backend', 'High', 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-030', 'Irrelevant AI Hypotheses in Discovery Feature due to Inaccurate Web Scraping', 'Description: Irrelevant AI Hypotheses in Discovery Feature due to Inaccurate Web Scraping
Pre-conditions: Client domain configured with secondary or career subpages.
Steps: 1. Run Discovery feature analysis on target domain. 2. Inspect generated strategy hypotheses.
Expected: Discovery engine scrapes primary product/services site data and outputs relevant business hypotheses (avoids real estate "Fix & Flip" suggestions for B2C).', 'Backend', 'High', 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-031', 'Mandatory "Job Title" Field Creates Friction for B2C Client Onboarding', 'Description: Mandatory "Job Title" Field Creates Friction for B2C Client Onboarding
Pre-conditions: User filling out Client Onboarding Form for B2C profile.
Steps: 1. Leave "Job Title" field empty on onboarding form. 2. Attempt to proceed to next step.
Expected: System allows "Job Title" to be optional or adapts fields dynamically based on B2B vs. B2C strategy context.', 'UX', 'High', 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-032', 'Extension link in client portal missing from left navigation menu', 'Description: Extension link in client portal missing from left navigation menu
Pre-conditions: User is logged into the Client Portal.
Steps: 1. Log into the client portal. 2. Inspect the left navigation menu items.
Expected: The left navigation menu includes a direct link/item to download/access the Chrome Extension.', 'Backend', 'Critical', 'Reported', 'prod', 'Max', 'max@admin.reddit');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-033', 'User was frozen due to being "flagged by Reddit" - u/Lena_Gupta19 - the user isn''t shadowbanned nor flagged, false reporting', 'Description: User was frozen due to being "flagged by Reddit" - u/Lena_Gupta19 - the user isn''t shadowbanned nor flagged, false reporting
Pre-conditions: Client is XM Cyber
Steps: 1. Log into the client portal. 2. Inspect the voices section
Expected: The system will detect either a) why this account has been flagged or b) why was it frozen for no reason', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-034', 'Partner side - defined a strategy for client''s voice (LoanBase, u/need4speed8) - got as output 3 questions - unclear where should I/the client answer them', 'Description: Partner side - defined a strategy for client''s voice (LoanBase, u/need4speed8) - got as output 3 questions - unclear where should I/the client answer them
Pre-conditions: Client is LoanBase, client''s voice has ran a strategy generation
Steps: 1. Log into the partner portal 2. Went to LoanBase''s voice 3. Went to "Strategy" 4. Generated new strategy
Expected: A much clearer output as to where those questions could be answered or alternatively - the platform would suggest answers and the client/partner will approve/edit', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-035', 'Partner side - Buyer intent prompts on GEO/AEO: cannot enter new prompts manually. "Generate with AI" generates too few prompts - can''t add more if needed', 'Description: Partner side - Buyer intent prompts on GEO/AEO: cannot enter new prompts manually. "Generate with AI" generates too few prompts - can''t add more if needed
Steps: 1. Log into the partner portal 2. Went to clients > LoanBase 3. Clicked on GEO 4. Tried to enter prompts manually, clicked ''+'' without success
Expected: The ability to increase the number of high intent prompts beyone the initial AI generated prompts', 'Backend', NULL, 'Reported', 'prod', 'Tzvi', 'tzvi@gorampit.com');
INSERT INTO bug_reports (bug_id, title, problem, category, risk_level, status, environment, reporter, reporter_email) VALUES ('BUG-036', 'Clicking "Get Started" on pricing plans after free trial redirects to "Access Denied" error page , this link : https://staging.gorampit.com/clients/a368cabf-bcf0-4a82-be6e-ae4ef76612da/billing/change-', 'Description: Clicking "Get Started" on pricing plans after free trial redirects to "Access Denied" error page , this link : https://staging.gorampit.com/clients/a368cabf-bcf0-4a82-be6e-ae4ef76612da/billing/change-plan
Pre-conditions: New user in client portal whose free trial has ended.
Steps: 1. Navigate to Stripe plan selection page after free trial ends. 2. Click "Get Started" on any displayed plan.
Expected: User is redirected to the Stripe checkout flow successfully to complete payment.', 'Backend', 'Critical', 'Reported', 'prod', 'Jenny', 'jenny@gorampit.com');
-- Imported 35 bugs
