"""Pre-start features for the CollisionGuard product model.

Everything here is computed from the two task descriptions, the repository
tree, and optional agent identities. No changed files, diffs, or merge
outcomes are read.
"""

import math
import re

WORD = re.compile(r"[a-z0-9]+")

AGENT_ALIASES = {
    "codex": "OpenAI_Codex", "openai_codex": "OpenAI_Codex",
    "openai-codex": "OpenAI_Codex", "openaicodex": "OpenAI_Codex",
    "claude": "Claude_Code", "claude_code": "Claude_Code",
    "claude-code": "Claude_Code", "claudecode": "Claude_Code",
    "copilot": "Copilot", "github_copilot": "Copilot",
    "github-copilot": "Copilot", "githubcopilot": "Copilot",
    "devin": "Devin", "cursor": "Cursor",
    "jules": "Google_Jules", "google_jules": "Google_Jules",
    "google-jules": "Google_Jules",
}


TYPE_WORDS = {
    "docs": {"doc", "docs", "documentation", "readme", "changelog", "release",
             "guide", "comment", "typo"},
    "tests": {"test", "tests", "testing", "spec", "coverage", "fixture", "mock"},
    "deps": {"dependency", "dependencies", "bump", "upgrade", "version",
             "package", "lockfile", "requirements"},
    "ci": {"ci", "workflow", "github", "actions", "pipeline", "build"},
    "refactor": {"refactor", "cleanup", "rename", "move", "simplify", "reorganize"},
    "ui": {"ui", "button", "css", "style", "layout", "component", "frontend",
           "responsive", "modal"},
    "api": {"api", "endpoint", "route", "handler", "request", "response",
            "client", "sdk"},
    "db": {"database", "db", "schema", "migration", "query", "sql", "orm", "model"},
    "security": {"security", "auth", "permission", "token", "secret",
                 "vulnerability", "cve"},
    "perf": {"performance", "speed", "memory", "cache", "optimize", "latency"},
}


def normalize_agent(name):
    """Map common product spellings to the names used in training."""
    value = (name or "").strip()
    if not value:
        return "unknown"
    key = value.casefold().replace(" ", "_")
    return AGENT_ALIASES.get(key, value)


def tokens(text):
    return set(WORD.findall((text or "").lower()))


def pair_features(task_a, task_b, language=None, tree_files=0, same_agent=False,
                  agent_a=None, agent_b=None):
    """Return a feature dictionary for one task pair.

    Agent names are optional. When omitted, both sides use "unknown" and the
    model falls back to the shared task and repository features.
    """
    first, second = tokens(task_a), tokens(task_b)
    first_agent = normalize_agent(agent_a)
    second_agent = normalize_agent(agent_b)
    features = {
        "lang": language or "unknown",
        "tree": math.log1p(max(0, tree_files or 0)),
        "same": int(bool(same_agent)),
        "la": math.log1p(len(first)),
        "lb": math.log1p(len(second)),
        "agent_a": first_agent,
        "agent_b": second_agent,
        "agent_pair": first_agent + "+" + second_agent,
    }
    for name, words in TYPE_WORDS.items():
        in_a = bool(first & words)
        in_b = bool(second & words)
        features[f"type_{name}"] = int(in_a) + int(in_b)
        features[f"both_{name}"] = int(in_a and in_b)
    return features


REASON_LABELS = {
    "type_docs": "tasks mention documentation",
    "type_tests": "tasks mention tests",
    "type_deps": "tasks mention dependencies or versions",
    "type_ci": "tasks mention CI or build work",
    "type_refactor": "tasks mention refactoring",
    "type_ui": "tasks mention UI work",
    "type_api": "tasks mention API work",
    "type_db": "tasks mention database work",
    "type_security": "tasks mention security or auth",
    "type_perf": "tasks mention performance",
    "both_docs": "both tasks look like documentation work",
    "both_tests": "both tasks look like test work",
    "both_deps": "both tasks look like dependency updates",
    "both_ci": "both tasks look like CI work",
    "both_refactor": "both tasks look like refactors",
    "both_ui": "both tasks look like UI work",
    "both_api": "both tasks look like API work",
    "both_db": "both tasks look like database work",
    "both_security": "both tasks touch security or auth",
    "both_perf": "both tasks look like performance work",
    "same": "same agent on both tasks",
    "tree": "repository size",
    "la": "task A length",
    "lb": "task B length",
}


def reason_text(feature_name):
    if feature_name in REASON_LABELS:
        return REASON_LABELS[feature_name]
    if feature_name.startswith("lang="):
        return "repository language " + feature_name.split("=", 1)[1]
    return feature_name.replace("_", " ")
