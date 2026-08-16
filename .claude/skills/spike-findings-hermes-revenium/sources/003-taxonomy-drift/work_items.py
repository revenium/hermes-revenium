"""Work items for the fragmentation experiment.

Five distinct underlying activities. Items 1 and 4 are THE SAME activity described
differently (a flaky-test investigation) — that pair is the fragmentation probe:
a healthy vocabulary gives them one label, a fragmenting one gives them two.

Kept short so each classification is cheap.
"""

WORK = [
    {
        "id": "flaky-1",
        "activity": "flaky_test_investigation",
        "user": "The checkout tests pass locally but fail about one run in five on CI. Find out why.",
        "assistant": "It's a shared fixture: the cart is module-scoped, so a test that mutates it "
                     "leaks into the next one depending on ordering. Make it function-scoped.",
    },
    {
        "id": "perf-1",
        "activity": "query_performance_tuning",
        "user": "The dashboard endpoint takes 4 seconds. Make it faster.",
        "assistant": "The N+1 is in the org serializer — 340 queries per request. "
                     "A select_related on owner plus prefetch on members takes it to 3 queries, ~180ms.",
    },
    {
        "id": "docs-1",
        "activity": "api_documentation",
        "user": "Write the reference docs for the new webhooks endpoint.",
        "assistant": "Documented all six event types with payload schemas, the signature "
                     "verification flow, and the retry/backoff table.",
    },
    {
        "id": "flaky-2",
        "activity": "flaky_test_investigation",
        "user": "Our CI is red maybe 20% of the time on the same suite, but it's green when I run it. Dig in.",
        "assistant": "Order-dependent state: a module-scoped fixture is mutated by one test and "
                     "read by another. Scope it per-function and the intermittency goes away.",
    },
    {
        "id": "sec-1",
        "activity": "security_review",
        "user": "Review this auth middleware before we ship it.",
        "assistant": "Two issues: the token comparison isn't constant-time, and expiry is checked "
                     "before signature verification, so a forged token gets a different error.",
    },
]

# Items sharing an activity — used to compute the fragmentation ratio.
SAME_ACTIVITY_PAIRS = [("flaky-1", "flaky-2")]
DISTINCT_ACTIVITIES = len({w["activity"] for w in WORK})
