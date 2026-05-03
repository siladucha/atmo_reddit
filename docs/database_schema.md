# Database Schema - Reddit Engagement Engine

This document outlines the database tables required to run the Reddit Engagement workflows. You must create these tables in your Postgres/Supabase instance.

## Table: `clients`
**What it is:** One row per agency client. Holds everything about the company — their brand, strategy, positioning.
*   **client_id** (text, Primary Key)
*   **created_at** (timestamptz)
*   **client_name** (text)
*   **brand_name** (text)
*   **company_profile** (text)
*   **company_worldview** (text)
*   **company_problem** (text)
*   **competitive_landscape** (text)
*   **brand_voice** (text)
*   **case_studies** (text)
*   **icp_profiles** (text)
*   **keywords** (jsonb array)

## Table: `personas`
**What it is:** The strategic identity layer of a fictional Reddit avatar (what they believe, how they sound).
*   **id** (uuid, Primary Key)
*   **client_id** (text, FK to clients)
*   **platform** (text, e.g., 'reddit')
*   **persona_name** (text)
*   **voice_profile** (text)
*   **is_active** (boolean)

## Table: `client_subreddits`
**What it is:** The list of subreddits we scrape and monitor for a given client.
*   **id** (uuid, Primary Key)
*   **client_id** (text, FK to clients)
*   **subreddit_name** (text)
*   **type** (text, 'primary' or 'secondary')
*   **is_active** (boolean)

## Table: `reddit_avatars`
**What it is:** The operational Reddit account layer. Holds credentials, karma tracking, account history, and subreddit subscriptions.
*   **item_id** (text/nanoid, Primary Key)
*   **client_id** (text array)
*   **active** (boolean)
*   **reddit_username** (text)
*   **email_address** / **email_password** / **reddit_password** (text - credentials)
*   **hobby_sub-reddits** (jsonb array)
*   **voice_profile_md** / **tone_principles** / **speech_patterns** (text)
*   **hill_i_die_on** / **helpful_mode_topics** (text)
*   **constraints** / **vocabulary_lean** (text)

## Table: `reddit_threads`
**What it is:** Scraped Reddit threads — one row per thread per client. Covers both professional (scored) and hobby (karma-building) pipelines.
*   **id** (text, Primary Key)
*   **client_id** (text, FK to clients)
*   **type** (text, 'professional' or 'hobby')
*   **reddit_native_id** (text)
*   **subreddit** (text)
*   **post_title** / **post** / **comments** / **url** / **author** (text)
*   **tag** (text, 'engage', 'monitor', 'skip' - for professional)
*   **relevance** / **quality** / **strategic** / **composite** (numeric scores)
*   **intent** (text)

## Table: `hobby_subreddits`
**What it is:** Storage for hobby subreddit posts and their AI-generated comments. Used exclusively by the hobby pipeline.
*   **id** (text/uuid, Primary Key)
*   **url** / **permalink** (text)
*   **created** / **scraped_at** (timestamptz)
*   **author** / **avatar_username** (text)
*   **content** / **post** / **comments** / **post_title** (text)
*   **post_image** (jsonb array)
*   **post_ups** / **post_downs** (numeric)
*   **post_id** / **subreddit** / **subreddit_id** (text)
*   **ai_comment** (text)
*   **status** (text)

## Table: `reddit_comment_drafts`
**What it is:** One comment draft per avatar per thread.
*   **id** (text, Primary Key)
*   **reddit_threads_item_id** (text, FK to reddit_threads)
*   **client_id** (text, FK to clients)
*   **avatar_id** (text, FK to reddit_avatars)
*   **type** (text, 'professional' or 'hobby')
*   **ai_draft** (text)
*   **published_comment** (text)
*   **status** (text, 'pending', 'approved', 'rejected', 'posted')
*   **engagement_mode** (text, 'bullseye', 'helpful_peer', 'karma_only')
*   **engagement_angle** (text - for hobby)

## Table: `reddit_post_drafts`
**What it is:** AI-generated Reddit posts.
*   **id** (text/nanoid, Primary Key)
*   **client_id** (text, FK to clients)
*   **avatar_id** (text, FK to reddit_avatars)
*   **subreddit** (text)
*   **ai_title** / **ai_body** (text)
*   **status** (text, 'pending', 'approved', 'rejected', 'posted')
*   **source_item_id** (text, FK to news_scrape)

## Table: `news_scrape`
**What it is:** Scraped news/Reddit content used as raw material for the Reddit post creation pipeline.
*   **item_id** (text/nanoid, Primary Key)
*   **client_id** (text, FK to clients)
*   **url** / **title** / **content** / **summary** / **source** (text)
*   **content_type** (text, 'news', 'reddit_post')

## Table: `parallel_job_results`
**What it is:** Infrastructure table for n8n parallel job execution.
*   **id** (serial, Primary Key)
*   **job_id** (text)
*   **item_index** / **total_items** (numeric)
*   **resume_url** (text)
*   **result_json** (text)
