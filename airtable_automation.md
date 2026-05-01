# Airtable Automation: Comment Sent

This guide explains the Airtable automation needed for the Reddit engagement workflows.

## What You Need to Know About Airtable Exports

Airtable does **not** let you export a full base with all its automations and interfaces in one click. 
- You can get the tables, fields, and views using the Airtable API.
- You must build the automations and interfaces by hand.

Because you have to build automations by hand, here is the setup for the `comment_sent` automation.

---

## Automation Name: `comment_sent`

This automation sends a signal to n8n when a comment is ready to post.

### 1. The Trigger
* **Type:** When a record matches conditions
* **Table:** Reddit Comments
* **Condition:** The `comment_sent` box is checked.

### 2. The Action
* **Type:** Run a script
* **Input Variables to Set:**
  * `recordId`: The Airtable record ID.
  * `webhook`: The n8n webhook URL.
  * `action`: The action name (if you use one).

* **The Code:**
  ```javascript
  let autoRoute = input.config();
  await fetch(autoRoute.webhook + "?recordId=" + autoRoute.recordId + "&action=" + autoRoute.action);
  ```

* **What the code does:** The script takes your variables. It then sends a web request to the n8n webhook link. It adds the record ID and action to the end of the link so n8n knows which comment to post.
