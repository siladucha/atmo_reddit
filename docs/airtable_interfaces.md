# Airtable Interfaces: UI Setup Guide

This document explains how the Airtable Interfaces are built for the Reddit engagement project. You cannot export interfaces automatically, so you will need to build these manually using the Airtable Interface Designer.

The "XM Cyber" interface has four main pages:
1. Reddit Comments
2. Reddit posts
3. Reddit Comments tracking
4. Reddit Posts tracking

---

## 1. Reddit Comments Page

**Goal:** Review and approve AI-generated comments before sending them to Reddit.

**Page Layout:** Record Review (Left sidebar with a list, right panel for details)

### Left Sidebar Setup
*   **Source:** Reddit Comments table
*   **Group By:** `Persona`
*   **List Item Settings:**
    *   **Title:** `Title`
    *   **Field 1:** `alert`
    *   **Field 2:** `post ups`

### Right Details Panel Setup
*   **Title Field:** `Title` (Size: Large or X-Large)
*   **Visible Fields (in order):**
    *   `Post` (The original Reddit post content)
    *   `post ups`
    *   `Comment to` (Context on who we are replying to)
    *   `Comment` (The AI generated comment, editable)
    *   `Location depth`
    *   `Refined Version` (Empty text box for human edits)
    *   `Location Reasoning`
    *   `alert`
    *   `Comment Approach`
    *   `Perspective Push`
    *   `Brand Mention`
    *   `url` (Link to the Reddit thread)
    *   **`comment_sent` (Checkbox to trigger the n8n automation)**
    *   `post downs`
    *   `Persona`
    *   `subreddit`
    *   `created`
    *   `Version (for Ori)`
*   **Buttons:** Include a "Delete record" button at the top right.

---

## 2. Reddit Posts Page

**Goal:** Review and approve full Reddit posts drafted by the AI.

**Page Layout:** Record Review

### Left Sidebar Setup
*   **Source:** Reddit posts table
*   **Filter:** Has 2 active conditions (e.g., Status is not "Posted")
*   **List Item Settings:**
    *   **Title:** `Post Title`
    *   **Field 1:** `Subreddit`

### Right Details Panel Setup
*   **Title Field:** `Post Title` (Size: Large or X-Large)
*   **Visible Fields (in order):**
    *   `Post Title`
    *   `Post Body` (The drafted post content)
    *   `Avatar`
    *   `Subreddit`
    *   `Status` (Dropdown, e.g., "Pending")
    *   `Worldview Seed`
    *   `Post Type` (e.g., "industry_hot_take")
    *   `Strategic Tier`
    *   `Engagement Mode`
    *   `Date`
    *   `Source URL` (Link to the news article used for the post)
*   **Buttons:** Include a "Delete record" button at the top right.

---

## 3. Reddit Comments Tracking Page

**Goal:** A high-level view of all comments and their statuses.

**Page Layout:** List

*   **Source:** Reddit Comments table
*   **Visualizations:** List
*   **Columns to Display:**
    *   `Refined Version`
    *   `AI Suggested Comment`
    *   `Comment to`
    *   `Persona`

---

## 4. Reddit Posts Tracking Page

**Goal:** A high-level view of all drafted posts.

**Page Layout:** List

*   **Source:** Reddit Posts table
*   **Visualizations:** List
*   *(Similar column setup as the comments tracking page, focusing on post status, title, and persona)*
