"""Launch text for the About, policy and contact pages.

`bootstrap_site` creates each page once, as an unpublished draft, from these
definitions; after that the page belongs to the editors (edited in Wagtail,
never overwritten). Publisher details (legal name, address, grievance
officer…) are not written into the text: the `contact_details` block shows
them from Settings → Site settings, so every page stays consistent.

The legal pages are starting drafts written for this product as it works
today (no reader accounts, payments, analytics or ads). Have them reviewed
by a lawyer before publishing, and update them when those features arrive.
"""

# key used in templates (trust_pages.<key>) → page slug
TRUST_PAGE_SLUGS = {
    "about": "about",
    "ai_policy": "ai-policy",
    "corrections": "corrections",
    "contact": "contact",
    "grievances": "grievances",
    "terms": "terms",
    "privacy": "privacy",
}


def heading(text):
    return {"type": "heading", "value": text}


def paragraph(html):
    return {"type": "paragraph", "value": html}


def points(title, items):
    return {"type": "key_points", "value": {"title": title, "points": items}}


def contact(kind):
    return {"type": "contact_details", "value": {"kind": kind}}


ABOUT = {
    "slug": "about",
    "title": "About us",
    "intro": (
        "An analysis-led publication about India and its place in the world: news, analysis and "
        "explainers that put context before speed."
    ),
    "search_description": "Who we are, how our newsroom works and the standards we hold ourselves to.",
    "body": [
        heading("Who we are"),
        paragraph(
            "<p>We cover politics, the economy, cities, society, education, health, science and India's "
            "relations with the world. We try to explain not just what happened, but why it matters and what "
            "is likely to happen next.</p>"
            "<p>We are independent. We have no affiliation with any political party, and our editors alone "
            "decide what we publish.</p>"
        ),
        heading("How our newsroom works"),
        paragraph(
            "<p>Our articles are produced by AI agents working under human editors. Editors decide what we "
            "cover; agents research each topic from published sources, write a draft, check the facts and edit. An editor reviews "
            "every article, and nothing is published without an editor's approval. Every article produced this "
            'way is labelled, and our <a href="/ai-policy/">AI policy</a> explains exactly what the agents do '
            "and what they never do.</p>"
        ),
        heading("Our standards"),
        points(
            "What you can expect from us",
            [
                "Accuracy first: claims are checked against their sources before publication, and we say so when something cannot be verified.",
                "Clear sourcing: we link to primary documents, official data and the reporting we rely on, and list our sources at the end of each article.",
                "No invented people, quotes or events, ever.",
                "News and analysis kept apart from opinion, and every article labelled with its type.",
                "Mistakes corrected openly, with a note on the article saying what changed.",
            ],
        ),
        heading("Article types"),
        paragraph(
            "<ul><li><b>News</b> reports what has happened, as fully and fairly as we can establish it.</li>"
            "<li><b>Analysis</b> goes behind the news to explain causes, consequences and trade-offs.</li>"
            "<li><b>Explainer</b> sets out the background to a complex subject so that you can follow the "
            "debate.</li>"
            "<li><b>Opinion</b>, when we publish it, is a signed argument by a named person. AI agents never "
            "write opinion or editorials.</li></ul>"
        ),
        heading("Get in touch"),
        paragraph(
            '<p>To report an error, see our <a href="/corrections/">corrections policy</a>. For everything '
            'else, including formal complaints, see <a href="/contact/">Contact us</a>.</p>'
        ),
    ],
}

AI_POLICY = {
    "slug": "ai-policy",
    "title": "How we use AI",
    "intro": (
        "Most of our journalism is produced with AI agents. This page explains what they do, what they never "
        "do, and who is accountable for what we publish."
    ),
    "search_description": "What our AI agents do, what they never do, and how editors stay accountable.",
    "body": [
        heading("What the agents do"),
        points(
            "Each article passes through several agents",
            [
                "Research the topic set in the editor's brief from published sources (official documents, data and other reporting) and keep a record of every source used.",
                "Analyse the material, outline the article and write a draft in our house style.",
                "Fact-check the draft against the sources and flag any claim that the sources do not support.",
                "Edit for clarity, accuracy and length, and suggest a headline and summary.",
            ],
        ),
        heading("What the agents never do"),
        points(
            "Our rules",
            [
                "Publish: every article is approved and published by a human editor.",
                "Write opinion pieces or editorials.",
                "Invent people, quotes, experiences or events, or write in the first person as if they were a reporter.",
                "Create images presented as photographs. Any generated illustration is labelled as an illustration.",
                "See readers' personal data: they work only from published sources and the article's brief.",
            ],
        ),
        heading("Human accountability"),
        paragraph(
            "<p>An editor reviews every article before it is published. The editor can send it back for "
            "changes, rewrite parts of it, or reject it. Once published, an article is our responsibility "
            "exactly as if a human reporter had written it, and our "
            '<a href="/corrections/">corrections policy</a> and <a href="/grievances/">grievance process</a> '
            "apply in full.</p>"
        ),
        heading("How you can tell"),
        paragraph(
            "<p>Every article produced with AI agents carries an <b>AI-assisted</b> label, and a note at the "
            "foot of the article explains how AI was used. The sources the article relies on are listed and "
            "linked at the end.</p>"
        ),
        heading("The technology"),
        paragraph(
            "<p>The agents run on large language models (currently Claude, made by Anthropic). Such models can "
            "make mistakes, including confident-sounding ones. Our fact-checking step and editorial review are "
            "designed to catch them; if you spot one we missed, please "
            '<a href="/corrections/">tell us</a>.</p>'
            "<p>We review this policy as the technology and our practice change. The date of the last update "
            "is shown at the bottom of this page.</p>"
        ),
    ],
}

CORRECTIONS = {
    "slug": "corrections",
    "title": "Corrections policy",
    "intro": "We correct our mistakes promptly and openly.",
    "search_description": "How we correct mistakes, and how to report one.",
    "body": [
        heading("How we correct"),
        paragraph(
            "<p>When an article gets a fact wrong, we fix it and add a correction note at the foot of the "
            "article, dated, saying what was wrong and what we changed. A corrected article shows "
            "<b>Corrected</b> next to its date, so readers who saw the earlier version can tell.</p>"
            "<p>Small fixes to spelling, grammar or style that do not change the meaning are made without a "
            "note.</p>"
        ),
        heading("Reporting an error"),
        paragraph(
            "<p>Write to us with a link to the article and a description of the mistake. We read every report. "
            "If you want a formal decision on a complaint, including under the Information Technology "
            "(Intermediary Guidelines and Digital Media Ethics Code) Rules, 2021, use our "
            '<a href="/grievances/">grievance process</a>.</p>'
        ),
        contact("corrections"),
        heading("Recent corrections"),
        {"type": "recent_corrections", "value": {"count": 30}},
    ],
}

CONTACT = {
    "slug": "contact",
    "title": "Contact us",
    "intro": "How to reach the publisher, report an error, make a complaint or ask about your personal data.",
    "search_description": "Contact details for the publisher, corrections, complaints and personal data questions.",
    "body": [
        heading("The publisher"),
        contact("publisher"),
        heading("Report an error"),
        paragraph('<p>See our <a href="/corrections/">corrections policy</a>.</p>'),
        contact("corrections"),
        heading("Complaints"),
        paragraph(
            "<p>Formal complaints about our content go to our Grievance Officer. The quickest way is our "
            '<a href="/grievances/">complaint form</a>, which gives you a reference number straight away.</p>'
        ),
        contact("grievance"),
        heading("Your personal data"),
        paragraph(
            '<p>For questions about your personal data or to exercise your rights, see our '
            '<a href="/privacy/">privacy policy</a> or write to:</p>'
        ),
        contact("privacy"),
    ],
}

TERMS = {
    "slug": "terms",
    "title": "Terms of use",
    "intro": "The terms that apply when you use this website. By using it, you accept them.",
    "search_description": "The terms that apply when you use this website.",
    "body": [
        heading("Who we are"),
        paragraph(
            "<p>In these terms, “we”, “us” and “our” mean the publisher of this website, whose details are "
            "below, and “you” means anyone using the website.</p>"
        ),
        contact("publisher"),
        heading("Our content"),
        paragraph(
            "<p>The articles, images, graphics and design on this website belong to us or to the people who "
            "licensed them to us, and are protected by copyright.</p>"
            "<p>You may read, share links to, and print or save our articles for your own personal, "
            "non-commercial use, and quote short extracts if you credit us and link to the article.</p>"
            "<p>Without our written permission you may not republish whole articles or substantial parts of "
            "them, copy our content systematically, or use automated tools to extract it, including for "
            "building datasets or training artificial intelligence systems.</p>"
        ),
        heading("Accuracy and AI-assisted journalism"),
        paragraph(
            "<p>We work hard to be accurate, and we explain how our articles are produced, including our use "
            'of AI agents under editorial supervision, in our <a href="/ai-policy/">AI policy</a>. Our content '
            "is general information, not professional advice: do not rely on it for financial, legal, medical "
            "or other decisions without taking advice suited to your circumstances. When we get something "
            'wrong, we correct it under our <a href="/corrections/">corrections policy</a>.</p>'
        ),
        heading("Using the website"),
        paragraph(
            "<p>You must not use the website unlawfully, try to gain unauthorised access to it or to our "
            "systems, interfere with its operation (for example by overloading it), or introduce malicious "
            "code. When you write to us or use our forms, do not send material that is unlawful, abusive or "
            "that infringes anyone else's rights.</p>"
        ),
        heading("Links to other websites"),
        paragraph(
            "<p>We link to other websites, especially our sources. We are not responsible for their content or "
            "for how they handle your data.</p>"
        ),
        heading("Availability and liability"),
        paragraph(
            "<p>We provide the website as it is and cannot promise that it will always be available or free of "
            "errors. To the extent the law allows, we are not liable for any indirect or consequential loss "
            "arising from your use of the website. Nothing in these terms limits any liability that cannot be "
            "limited under Indian law.</p>"
        ),
        heading("Complaints"),
        paragraph(
            '<p>Complaints about our content are handled through our <a href="/grievances/">grievance '
            "process</a>.</p>"
        ),
        heading("Changes and governing law"),
        paragraph(
            "<p>We may update these terms; the date of the last update is shown at the bottom of this page, and "
            "the version published here applies from that date.</p>"
            "<p>These terms are governed by the laws of India. The courts at the place of our registered office "
            "(above) have jurisdiction over any dispute arising from them, without affecting any rights you "
            "have under law that cannot be excluded.</p>"
        ),
    ],
}

PRIVACY = {
    "slug": "privacy",
    "title": "Privacy policy",
    "intro": (
        "What personal data we collect when you use this website, why we use it, who we share it with, and "
        "your rights under the Digital Personal Data Protection Act, 2023."
    ),
    "search_description": "What personal data we collect, why, and your rights under the DPDP Act 2023.",
    "body": [
        heading("Who is responsible"),
        paragraph(
            "<p>The publisher named below decides how and why your personal data is processed on this website "
            "and is the Data Fiduciary responsible for it under the Digital Personal Data Protection Act, "
            "2023.</p>"
        ),
        contact("publisher"),
        paragraph("<p>Questions about your personal data, and requests to exercise your rights, go to:</p>"),
        contact("privacy"),
        heading("What we collect"),
        points(
            "Personal data we process",
            [
                "When you read the website: you do not need an account, and we use no analytics or advertising trackers. To deliver pages, keep the website secure and fix problems, our servers and our security and delivery provider (Cloudflare) automatically process technical data: your IP address, browser type, the pages you request and when.",
                "When you write to us or use our complaint form: your name, contact details and whatever you tell us.",
                "Newsroom staff: the account details needed to sign in to our editing system.",
            ],
        ),
        heading("Why we use it"),
        points(
            "Purposes",
            [
                "To deliver the website, keep it secure and fix faults.",
                "To answer your messages, investigate and decide complaints, and correct errors.",
                "To meet our legal obligations, including record-keeping and reporting under the Information Technology Rules, 2021, and requests from authorities where the law requires us to comply.",
            ],
        ),
        paragraph(
            "<p>We do not sell your personal data, use it for advertising, or give it to the AI systems that "
            "help produce our articles.</p>"
        ),
        heading("Cookies"),
        paragraph(
            "<p>We set no cookies to track readers. A security cookie is set when you submit a form, to protect "
            "against forged submissions, and Cloudflare may set a cookie that helps it tell people from "
            "automated traffic. Newsroom staff who sign in receive a session cookie. These cookies are needed "
            "for the website to work and are not used to follow you around the web.</p>"
        ),
        heading("Who we share it with"),
        paragraph(
            "<p>We use service providers who process data on our behalf and under our instructions: our "
            "hosting provider (servers and database), Cloudflare (delivery and security), our email provider "
            "(to send and receive messages) and our error-monitoring service (which receives technical "
            "details of faults, configured to exclude personal data such as IP addresses). Some of them "
            "process data outside India, as the law permits. We disclose personal data to authorities only "
            "when the law requires it.</p>"
        ),
        heading("How long we keep it"),
        paragraph(
            "<p>Server logs are kept for a limited period for security and troubleshooting, then deleted. "
            "Messages and complaints are kept for as long as we need them to deal with the matter and to meet "
            "our legal obligations, then deleted.</p>"
        ),
        heading("Your rights"),
        points(
            "Under the DPDP Act you can",
            [
                "Ask for a summary of the personal data we hold about you and how we use it.",
                "Ask us to correct, complete or update it.",
                "Ask us to erase it, unless the law requires us to keep it.",
                "Withdraw any consent you have given, as easily as you gave it.",
                "Nominate someone to exercise your rights if you die or become unable to.",
                "Have your grievance about how we handle your data addressed by us.",
            ],
        ),
        paragraph(
            "<p>Write to the contact above to exercise these rights. If you are not satisfied with our "
            "response, you can complain to the Data Protection Board of India.</p>"
        ),
        heading("Children"),
        paragraph(
            "<p>This website is written for a general adult audience. We do not knowingly collect personal "
            "data from children (people under 18). If you believe a child has sent us personal data, contact "
            "us and we will delete it.</p>"
        ),
        heading("Security"),
        paragraph(
            "<p>The website is served only over encrypted connections, access to personal data is limited to "
            "the staff who need it, and newsroom sign-in is protected by a second verification step.</p>"
        ),
        heading("Changes to this policy"),
        paragraph(
            "<p>We will update this policy when what we collect or how we use it changes, for example if we "
            "introduce reader accounts or subscriptions. The date of the last update is shown at the bottom "
            "of this page.</p>"
        ),
    ],
}

STANDARD_PAGES = [ABOUT, AI_POLICY, CORRECTIONS, CONTACT, TERMS, PRIVACY]

GRIEVANCES = {
    "slug": "grievances",
    "title": "Grievance redressal",
    "intro": (
        "<p>We follow the Code of Ethics for publishers of news and current affairs content in the Information "
        "Technology (Intermediary Guidelines and Digital Media Ethics Code) Rules, 2021. If you believe something "
        "we published breaks that Code, or is inaccurate, unfair or harmful, you can complain to our Grievance "
        "Officer using the form below, by email or by post.</p>"
        "<p><b>What happens next:</b> you get an acknowledgement with a reference number straight away by email. "
        "The Grievance Officer looks into your complaint and tells you the decision within 15 days of receiving "
        "it.</p>"
    ),
    "thank_you_text": (
        "<p>Thank you. Your complaint has been received and sent to our Grievance Officer. We have emailed you "
        "an acknowledgement; you will hear our decision within 15 days.</p>"
    ),
    "subject": "New complaint",
    "search_description": "How to complain to our Grievance Officer, and what happens next.",
    # label, field type, required, choices (newline-separated), help text
    "fields": [
        ("Your name", "singleline", True, "", ""),
        ("Email address", "email", True, "", "We send the acknowledgement and our decision here."),
        ("Phone number", "singleline", False, "", ""),
        ("Link to the content", "url", False, "", "The address of the article or page you are complaining about."),
        (
            "What is your complaint about?",
            "dropdown",
            True,
            # Wagtail splits choices on "\r\n", the line break browsers submit.
            "\r\n".join(
                [
                    "A factual error",
                    "A breach of the Code of Ethics (Norms of Journalistic Conduct)",
                    "My privacy or personal information",
                    "Defamation",
                    "Copyright",
                    "Something else",
                ]
            ),
            "",
        ),
        ("Your complaint", "multiline", True, "", "What is wrong, and what you would like us to do."),
        (
            "I confirm that the information in this complaint is true to the best of my knowledge",
            "checkbox",
            True,
            "",
            "",
        ),
    ],
}
