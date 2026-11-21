"""Repository file listing, language detection, and path ranking."""

import re
import subprocess
from pathlib import Path, PurePosixPath

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

EXTENSIONS = {
    ".py": "Python", ".pyi": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".cs": "C#",
    ".php": "PHP", ".rb": "Ruby", ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
    ".c": "C", ".h": "C", ".kt": "Kotlin", ".swift": "Swift", ".scala": "Scala",
    ".ex": "Elixir", ".exs": "Elixir", ".jl": "Julia", ".sh": "Shell",
    ".ps1": "PowerShell", ".m": "Objective-C", ".lua": "Lua", ".dart": "Dart",
    ".vue": "Vue", ".svelte": "Svelte", ".fs": "F#", ".fsx": "F#",
}


def list_repo_files(repo_path):
    """Return tracked files at HEAD, or files on disk when Git is unavailable."""
    repo = Path(repo_path)
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "-z", "HEAD"],
            capture_output=True, check=True, timeout=60,
        )
        paths = [part.decode("utf-8", "replace") for part in result.stdout.split(b"\0") if part]
        if paths:
            return paths
    except (subprocess.SubprocessError, OSError):
        pass
    return sorted(
        str(path.relative_to(repo)).replace("\\", "/")
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.parts
    )


def language_from_files(paths):
    counts = {}
    for path in paths:
        suffix = PurePosixPath(path).suffix.lower()
        language = EXTENSIONS.get(suffix)
        if language:
            counts[language] = counts.get(language, 0) + 1
    if not counts:
        return "unknown"
    return max(counts, key=lambda key: (counts[key], key))


def predict_files(task, file_paths, top_k=5):
    """Rank repository paths by character n-gram similarity to the task text."""
    if top_k <= 0 or not file_paths:
        return []
    text = (task or "").strip()
    if not text:
        return sorted([(path, 0.0) for path in file_paths])[:top_k]
    documents = [" ".join(re.findall(r"[a-z0-9]+", path.lower())) for path in file_paths]
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True)
    matrix = vectorizer.fit_transform([text] + documents)
    scores = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
    ranked = sorted(zip(file_paths, (float(score) for score in scores)),
                    key=lambda item: (-item[1], item[0]))
    return ranked[:top_k]


def shared_files(paths_a, paths_b):
    return sorted(set(paths_a) & set(paths_b))


def shared_directories(paths_a, paths_b):
    def parent(path):
        value = str(PurePosixPath(path).parent)
        return "" if value == "." else value
    return sorted({parent(path) for path in paths_a} & {parent(path) for path in paths_b})
