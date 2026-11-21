import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.file_predictor import (
    get_repository_files,
    predict_files_tfidf,
)

# Use the current CollisionGuard repository.
repo_path = REPO_ROOT

files = get_repository_files(str(repo_path))

print("Repository:", repo_path)
print("Total tracked files:", len(files))

task = "Update ParallACT data collection and merge replay scripts"

predictions = predict_files_tfidf(
    task_description=task,
    file_paths=files,
    top_k=5,
)

print("\nPredicted files:")
for path, score in predictions:
    print(f"{path}: {score:.3f}")
