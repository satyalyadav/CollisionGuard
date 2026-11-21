import subprocess
import re
from pathlib import PurePosixPath
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

def tokenize(text: str) -> set[str]:
    """Convert text into lowercase tokens."""
    # Split words on punctuation, underscores, and path separators.
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def predict_files(
    task_description: str,
    file_paths: list[str],
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Rank repository files by lexical overlap with a task description.

    The returned scores are ranking scores, not probabilities.
    """
    if top_k <= 0:
        return []

    task_tokens = tokenize(task_description)

    results = []

    for file_path in file_paths:
        # Include both the full path and the filename.
        path = PurePosixPath(file_path)
        file_tokens = tokenize(str(path))

        if not task_tokens or not file_tokens:
            score = 0.0
        else:
            # Fraction of task words that also appear in the file path.
            overlap = len(task_tokens & file_tokens)
            score = overlap / len(task_tokens)

        results.append((file_path, score))

    # Sort by score, then by path for deterministic results.
    results.sort(key=lambda item: (-item[1], item[0]))

    return results[:top_k]

def predict_files_tfidf(
    task_description: str,
    file_paths: list[str],
    top_k: int = 5,
) -> list[tuple[str, float]]:
    """
    Rank repository files using TF-IDF and cosine similarity.

    Scores measure text similarity, not conflict probability.
    """
    if top_k <= 0 or not file_paths:
        return []

    if not task_description.strip():
        return sorted(
            [(path, 0.0) for path in file_paths],
            key=lambda item: item[0],
        )[:top_k]

    # Convert file paths into searchable text.
    file_documents = [
        " ".join(re.findall(r"[a-z0-9]+", path.lower()))
        for path in file_paths
    ]

    # Use both word and character n-grams.
    vectorizer = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        lowercase=True,
    )

    documents = [task_description] + file_documents
    features = vectorizer.fit_transform(documents)

    task_vector = features[0:1]
    file_vectors = features[1:]

    similarities = cosine_similarity(
        task_vector,
        file_vectors,
    ).ravel()

    results = [
        (path, float(score))
        for path, score in zip(file_paths, similarities)
    ]

    results.sort(key=lambda item: (-item[1], item[0]))

    return results[:top_k]


def calculate_file_overlap(
    task_a: str,
    task_b: str,
    file_paths: list[str],
    top_k: int = 5,
    min_similarity: float = 0.1,
) -> dict:
    """
    Predict likely files for two tasks and calculate overlap.

    Low-scoring files are excluded using min_similarity.
    Jaccard similarity is not a conflict probability.
    """
    if not 0.0 <= min_similarity <= 1.0:
        raise ValueError("min_similarity must be between 0 and 1")

    predictions_a = predict_files_tfidf(
        task_a, file_paths, top_k=top_k
    )
    predictions_b = predict_files_tfidf(
        task_b, file_paths, top_k=top_k
    )

    # Remove files with low similarity scores.
    predictions_a = [
        (path, score)
        for path, score in predictions_a
        if score > 0 and score >= min_similarity
    ]

    predictions_b = [
        (path, score)
        for path, score in predictions_b
        if score > 0 and score >= min_similarity
    ]

    files_a = {path for path, _ in predictions_a}
    files_b = {path for path, _ in predictions_b}

    shared_files = files_a & files_b
    all_files = files_a | files_b

    jaccard = (
        len(shared_files) / len(all_files)
        if all_files else 0.0
    )

    return {
        "task_a_files": predictions_a,
        "task_b_files": predictions_b,
        "shared_files": sorted(shared_files),
        "overlap_count": len(shared_files),
        "jaccard_similarity": jaccard,
    }


def get_repository_files(repo_path: str) -> list[str]:
    """
    Get tracked files from a local Git repository.

    Returns repository-relative file paths.
    """
    result = subprocess.run(
        ["git", "-C", repo_path, "ls-files", "-z"],
        capture_output=True,
        check=True,
    )

    return [
        path.decode("utf-8", errors="replace")
        for path in result.stdout.split(b"\0")
        if path
    ]

if __name__ == "__main__":
    task = "Fix JWT authentication bug in the auth module"

    files = [
        "app/auth.py",
        "app/database.py",
        "app/security.py",
        "tests/test_auth.py",
    ]

    print("Lexical Overlap:")
    for path, score in predict_files(task, files, top_k=3):
        print(f"{path}: {score:.3f}")

    print("\nTF-IDF + Cosine Similarity:")
    for path, score in predict_files_tfidf(task, files, top_k=3):
        print(f"{path}: {score:.3f}")


    print("\nPredicted File Overlap:")

    task_a = "Fix JWT authentication bug"
    task_b = "Update authentication tests"

    overlap = calculate_file_overlap(
        task_a,
        task_b,
        files,
        top_k=2,
    )

    print("Task A files:", overlap["task_a_files"])
    print("Task B files:", overlap["task_b_files"])
    print("Shared files:", overlap["shared_files"])
    print("Overlap count:", overlap["overlap_count"])
    print("Jaccard similarity:", overlap["jaccard_similarity"])
