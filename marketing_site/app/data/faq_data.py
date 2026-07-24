"""FAQ content for the RAMP marketing site.

Single source of truth for FAQ entries displayed on both /pricing and /faq pages.
All content complies with RAMP client-facing language rules.
"""

FAQ_ITEMS: list[dict[str, str]] = [
    {
        "question": "Community Voice Protection Policy",
        "answer": (
            "We stand behind our community engagement management work. "
            "If a client-owned account becomes restricted or limited "
            "<strong>directly due to content we generated and approved</strong>, "
            "we provide 30 days of continued service at no additional charge "
            "to restore your presence with a replacement voice.<br><br>"
            "This protection covers restrictions attributable to RAMP-managed "
            "content (e.g., a community guideline violation that was not evident "
            "at the time of review). It does <strong>not</strong> cover:"
            "<ul class=\"mt-3 space-y-2 list-disc list-inside\">"
            "<li>Broad platform-wide policy changes or enforcement waves "
            "unrelated to your specific content.</li>"
            "<li>Restrictions caused by actions taken by you or your team "
            "outside of RAMP-managed activity.</li>"
            "<li>External platform changes that affect all users equally "
            "(e.g., new verification requirements).</li>"
            "</ul><br>"
            "Our human-in-the-loop process ensures every piece of content is "
            "reviewed before publication, significantly reducing the likelihood "
            "of any account becoming restricted. In the rare event it does occur, "
            "our team works to restore normal operations and adjust the "
            "persona-driven content strategy accordingly."
        ),
    },
    {
        "question": "How does RAMP differ from automated tools?",
        "answer": (
            "RAMP is a community engagement management platform built on a "
            "persona-driven content strategy — not an automation tool. "
            "Our process follows a strict 3-step human-in-the-loop workflow:"
            "<ul class=\"mt-3 space-y-2 list-disc list-inside\">"
            "<li><strong>Step 1:</strong> AI generates initial drafts tailored to "
            "each voice's expertise and the target community context.</li>"
            "<li><strong>Step 2:</strong> A human reviewer evaluates every draft "
            "for quality, relevance, tone, and community fit.</li>"
            "<li><strong>Step 3:</strong> Only explicitly approved content is "
            "published — nothing goes live without human sign-off.</li>"
            "</ul><br>"
            "No content is ever published without explicit human approval. "
            "This ensures every interaction is authentic, valuable to the "
            "community, and aligned with your brand voice."
        ),
    },
    {
        "question": "What results can I expect and when?",
        "answer": (
            "Our community engagement management approach follows a phased "
            "timeline designed for sustainable, long-term presence:"
            "<ul class=\"mt-3 space-y-2 list-disc list-inside\">"
            "<li><strong>Months 1–2 — Credibility Building:</strong> Voices "
            "establish themselves as genuine community participants through "
            "helpful, relevant contributions. You'll see growing recognition "
            "and positive reception from community members.</li>"
            "<li><strong>Months 3–4 — Presence Expansion:</strong> Content "
            "presence broadens across related communities. Voices become "
            "recognized contributors with established discussion history "
            "and community trust.</li>"
            "<li><strong>Month 5+ — Brand Integration:</strong> Organic "
            "opportunities arise for brand-relevant mentions within natural "
            "conversations. Community members begin associating your voices "
            "with subject-matter expertise.</li>"
            "</ul><br>"
            "We measure progress through qualitative indicators: community "
            "recognition, expert reputation, meaningful discussion participation, "
            "and growing brand association — rather than arbitrary numerical "
            "targets. Our human-in-the-loop process ensures quality at every stage."
        ),
    },
    {
        "question": "What happens if I already have existing community accounts?",
        "answer": (
            "We welcome clients with existing community presence. Our "
            "community engagement management process begins with a "
            "comprehensive <strong>pre-engagement audit</strong> that evaluates "
            "three key dimensions:"
            "<ul class=\"mt-3 space-y-2 list-disc list-inside\">"
            "<li><strong>Current Standing:</strong> How your existing voices are "
            "perceived within their communities.</li>"
            "<li><strong>Community Health:</strong> The overall environment and "
            "reception patterns in your active communities.</li>"
            "<li><strong>Strategic Alignment:</strong> How well existing presence "
            "maps to your business goals and target audience.</li>"
            "</ul><br>"
            "Existing accounts are incorporated into your persona-driven content "
            "strategy — never replaced or discarded. We build upon what you've "
            "already established, enhancing your presence with our human-in-the-loop "
            "quality process."
        ),
    },
    {
        "question": "Who writes the community engagement content?",
        "answer": (
            "Content creation is a collaborative process within our "
            "community engagement management platform. AI generates initial "
            "drafts tailored to each voice's persona, expertise, and the "
            "specific community context.<br><br>"
            "Every draft is then reviewed and approved by a human before "
            "publication — no content is published without this human-in-the-loop "
            "approval step. Each voice is backed by real subject-matter knowledge "
            "in their domain, ensuring the expertise represented is genuine "
            "rather than fabricated.<br><br>"
            "This persona-driven content strategy means your voices contribute "
            "authentically useful insights that community members genuinely "
            "value — building real reputation through real expertise."
        ),
    },
    {
        "question": "What's included in each plan?",
        "answer": (
            "Our community engagement management plans are structured to scale "
            "with your needs:"
            "<ul class=\"mt-3 space-y-2 list-disc list-inside\">"
            "<li><strong>Seed:</strong> 1 voice, 1 community, 30 actions/month "
            "— ideal for testing the waters.</li>"
            "<li><strong>Starter:</strong> 3 voices, 2 communities, 60 "
            "actions/month — establish initial presence.</li>"
            "<li><strong>Growth:</strong> 7 voices, 5 communities, 150 "
            "actions/month — expand your reach.</li>"
            "<li><strong>Scale:</strong> 15 voices, unlimited communities, "
            "400 actions/month — full market coverage.</li>"
            "</ul><br>"
            "All plans include our human-in-the-loop approval workflow, "
            "persona-driven content strategy, and community intelligence. "
            "For clients who want fully hands-off operation, a <strong>managed "
            "service add-on</strong> is available on any plan.<br><br>"
            "See the <a href=\"#pricing\" class=\"text-ramp-electric hover:underline\">"
            "pricing section above</a> for current rates and full plan comparison."
        ),
    },
    {
        "question": "How does RAMP handle external platform changes?",
        "answer": (
            "Our community engagement management platform operates on Reddit, "
            "which is an independent third-party service. Reddit may update its "
            "algorithms, moderation policies, or community guidelines at any time "
            "— and these changes can affect content visibility, community reach, "
            "or account standing for all users, including ours.<br><br>"
            "We do not control these external changes, but we actively monitor "
            "platform developments and adapt our persona-driven content strategy "
            "accordingly. Our team tracks policy updates, adjusts engagement "
            "patterns, and communicates with you when changes may affect your "
            "presence. This is part of the ongoing human-in-the-loop management "
            "we provide on every plan."
        ),
    },
    {
        "question": "Can activity frequency be adjusted for safety?",
        "answer": (
            "Yes. Our community engagement management approach prioritizes "
            "long-term account health over short-term volume. Each plan includes "
            "a monthly action limit, but we may temporarily reduce posting "
            "frequency for individual voices if our monitoring systems detect "
            "conditions that warrant caution.<br><br>"
            "This human-in-the-loop judgment call protects your investment — "
            "a brief pause is always preferable to a permanent restriction. "
            "We will notify you if frequency adjustments are needed and explain "
            "the reasoning. Once conditions normalize, regular activity resumes. "
            "Our persona-driven content strategy always adapts to current "
            "conditions rather than blindly following a fixed schedule."
        ),
    },
    {
        "question": "What should I know before connecting my own accounts?",
        "answer": (
            "We welcome clients who bring their own community accounts (BYOA). "
            "Our community engagement management onboarding includes a thorough "
            "audit of each account's current standing, community history, and "
            "strategic fit.<br><br>"
            "A few things to keep in mind:"
            "<ul class=\"mt-3 space-y-2 list-disc list-inside\">"
            "<li><strong>Account maturity matters:</strong> Newer accounts "
            "(under 3 months) or those with minimal community history may need "
            "a longer credibility-building period before achieving full impact.</li>"
            "<li><strong>Gradual integration:</strong> We ramp up activity slowly "
            "to maintain a natural engagement pattern. This means the first 2–4 "
            "weeks may have lower volume than your plan's full capacity.</li>"
            "<li><strong>Voice-community fit:</strong> Accounts work best when "
            "their existing history aligns with the target communities. We'll "
            "recommend the best fit during onboarding.</li>"
            "</ul><br>"
            "Our human-in-the-loop team assesses each account individually and "
            "provides honest recommendations. If an account isn't a strong fit, "
            "we'll tell you upfront rather than risk poor results."
        ),
    },
    {
        "question": "What's your cancellation policy?",
        "answer": (
            "Direct plans (Seed, Starter, Growth, Scale) have <strong>no "
            "long-term lock-in</strong>. You can cancel at any time, and your "
            "service access continues until the end of your current billing "
            "period.<br><br>"
            "Community reputation built by your voices during the subscription "
            "— including posted content, earned recognition, and authority "
            "established in communities — persists on the platform after "
            "cancellation. The value created through our community engagement "
            "management work remains yours.<br><br>"
            "Agency plans operate on annual contracts given the deeper "
            "integration and dedicated resources involved. Contact us for "
            "specific agency terms."
        ),
    },
]
