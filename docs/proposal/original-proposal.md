# Project Title: CollisionGuard

> Original proposal snapshot, preserved on 2026-11-07 from the supplied PDF. Public copy: student IDs have been removed; proposal content is otherwise unchanged apart from formatting and embedded links. The unchanged source copy remains local and is excluded from Git. Keep this file fixed; record later decisions and findings elsewhere.

## Team members

- Sourish Tiwari
- Satyal Yadav
- Yin Yao
- Kishore Kumar Varukolu

## Problem statement

As AI coding agents become more common, multiple agents may work on different tasks in the same repository at the same time. Although this can speed up development, overlapping changes may lead to textual merge conflicts, extra debugging, and delays. CollisionGuard aims to predict which pairs of coding tasks are likely to conflict before either agent starts writing code, using task descriptions and other information available beforehand. The goal is to help developers schedule tasks more intelligently, reducing conflicts without unnecessarily delaying independent work.

## Related work

Prior work investigates proactive collaboration-conflict detection [1] and merge-conflict prediction in software development [4], while CooperBench [2] and GitHub agent-PR studies [6] illustrate challenges for coding-agent collaboration. AIDev [3] provides historical coding-agent activity suitable for constructing candidate training data. A recent arXiv preprint [5] examines repository-lineage conflict signals and file-overlap forecasting; CollisionGuard focuses on predicting textual conflicts before either agent begins coding, using task descriptions and information available at that point.

[1] Yuriy Brun, Reid Holmes, Michael D. Ernst, and David Notkin. 2011. Proactive Detection of Collaboration Conflicts. In Proceedings of the 19th ACM SIGSOFT Symposium and the 13th European Conference on Foundations of Software Engineering (ESEC/FSE '11). ACM, 168–178. https://doi.org/10.1145/2025113.2025139

[2] Arpandeep Khatua, Hao Zhu, Peter Tran, Arya Prabhudesai, Frederic Sadrieh, Johann K. Lieberwirth, Xinkai Yu, Yicheng Fu, Michael J. Ryan, Jiaxin Pei, and Diyi Yang. 2026. CooperBench: Why Coding Agents Cannot be Your Teammates Yet. arXiv preprint arXiv:2601.13295. https://arxiv.org/abs/2601.13295

[3] Hao Li, Haoxiang Zhang, and Ahmed E. Hassan. 2026. AIDev: Studying AI Coding Agents on GitHub. arXiv preprint arXiv:2602.09185. https://arxiv.org/abs/2602.09185

[4] Moein Owhadi-Kareshk, Sarah Nadi, and Julia Rubin. 2019. Predicting Merge Conflicts in Collaborative Software Development. In Proceedings of the 2019 ACM/IEEE International Symposium on Empirical Software Engineering and Measurement (ESEM '19). IEEE, 1–11. https://doi.org/10.1109/ESEM.2019.8870173

[5] Arjun Subramanian, George Xu, and Nithilan Karthik. 2026. Asymmetric Repository Lineage Modeling and Verifier-Guided Coordination in Concurrent AI Coding Agents. arXiv preprint arXiv:2610.04779. https://arxiv.org/abs/2610.04779

[6] George Xu, Arjun Subramanian, and Nithilan Karthik. 2026. AI Agent Pull Requests on GitHub: Frequency, Structure, and Merge Conflict Rates. arXiv preprint arXiv:2607.04697. https://arxiv.org/abs/2607.04697

## Initial hypothesis

We hypothesize that combining task-description embeddings, pre-execution repository metadata, and predicted file-level overlap will improve textual merge-conflict prediction, measured by PR-AUC, compared with task-text similarity and logistic regression baselines. We further hypothesize that using these predictions to guide task scheduling will reduce simulated merge conflicts compared with unrestricted parallel execution while introducing less scheduling delay than broadly serializing tasks.

## Dataset(s)

### Dataset source (link and reference)

[AIDev v5](https://huggingface.co/datasets/hao-li/AIDev-7.6M) (Li et al., 2026; data cutoff March 31, 2026), focusing on its AIDev-pop subset (repositories with over 100 stars), which includes linked issues, PR commits, and file-level changes. We will pin the dataset revision; since v5 is still listed as work-in-progress, [AIDev v4](https://huggingface.co/datasets/hao-li/AIDev/tree/v4) is a fallback. Historical reference: the published 747-pair merge-replay sample ([Zenodo replication package](https://doi.org/10.5281/zenodo.21186464)). External evaluation: [CooperBench](https://arxiv.org/abs/2601.13295), if compatible textual-conflict labels can be generated.

### Number of instances

AIDev v5 contains 7,685,281 agent pull requests across 961,168 repositories overall; these are source totals, not the training-set size. We will construct issue-linked, co-active task pairs from AIDev-pop and report the usable pair count after filtering. The separate replication sample contains 747 pairs, including 716 with a usable merge-replay label. CooperBench provides 652 collaborative coding tasks across 12 repositories for possible external evaluation.

### Number of features

Per task: issue-text embeddings (dimension determined by the encoder), agent identity, and repository features available before coding begins. Per pair: embedding cosine similarity, same-agent indicator, pre-execution repository history, and predicted file-footprint overlap for the two-stage model. Conflict labels are prediction targets, not input features; actual PR completion times and observed execution overlap will not be used for prediction. Exact feature counts will be finalized after feature selection.

### Class distribution (# instances in each class, if applicable)

Binary target: textual Git merge conflict vs. clean merge. In the separate historical replication sample, 167 of 716 evaluable pairs conflict (23.3%) and 549 merge cleanly (76.7%); conflict rates are 119/601 (19.8%) for same-agent pairs and 48/115 (41.7%) for cross-agent pairs. These are not AIDev v5 class rates. We will report the distribution of our filtered task pairs and use PR-AUC and class weighting if the classes are imbalanced.

### Dataset splits

We will use repository-grouped cross-validation and a fully held-out set of repositories to prevent data leakage. We will also use a time-based split as a robustness check. Pairs sharing a PR will remain in the same fold. Before treating the published 747-pair replication sample as independent validation, we will check for and remove overlap with our training and tuning sets. We will use CooperBench for external evaluation only if compatible textual-conflict labels can be generated.

### Preprocessing steps

We will link historical PRs to their associated issues and use observed PR activity windows only to construct retrospective co-active task pairs, not as predictive features. We will remove pairs with missing base commits or unavailable references (UNAVAIL), generate textual-conflict labels using Git merge replay, clean duplicate or invalid issue descriptions, and truncate text for the embedding model. Prediction inputs will contain only information available before coding starts; completed PR timestamps, code diffs, and post-execution PR text will be excluded from model features. Git merge replay does not identify semantic conflicts in code that merges successfully.

## Method(s)

We will implement task-text similarity and logistic regression baselines, plus a direct gradient-boosted conflict classifier using task embeddings and repository features available before coding starts. For the two-stage model, we will train a file-footprint predictor on historical task descriptions paired with files modified in completed PRs as training labels; at inference, it will predict likely files using only pre-execution information, and a conflict classifier will use predicted overlap alongside repository features. Because a recent preprint reports textual conflicts even with disjoint authored-file sets [5], we will compare the two-stage model with the otherwise equivalent direct classifier and ablate the overlap feature. We plan to use Python, scikit-learn, and embedding models, and, if feasible, test a lightweight pretrained decision model as an additional baseline. Unlike open-PR scope forecasting or conflict models using completed PR state, CollisionGuard evaluates textual conflict risk before either agent begins writing code.

## Evaluation

We will measure textual merge-conflict prediction with PR-AUC as the primary metric, plus precision, recall, F1-score, and calibration. We will compare task-text similarity, logistic regression, direct gradient boosting, and the two-stage model on the same repository-held-out data, adding a pretrained decision model if feasible. To test the value and limits of file prediction, we will ablate predicted-overlap features and analyze missed conflicts for task pairs with disjoint versus overlapping authored file sets; observed file changes will be used only for retrospective error analysis. In scheduling simulation, we will report missed-conflict rate, the share of task pairs allowed to run in parallel, mean additional waiting time from task readiness to task start relative to unrestricted parallel execution, and end-to-end prediction latency, comparing against broad serialization under the same assumed task durations. We will inspect false positives and negatives and use repository-grouped and time-based splits to assess generalization.

## Management plan

We will divide the project into four tracks: Sourish Tiwari will handle data collection, task-pair construction, and merge-replay labeling; Satyal Yadav will develop baseline models, text-embedding features, the direct conflict classifier, and, if feasible, a pretrained decision-model comparison; Yin Yao will implement the file-footprint predictor and two-stage gradient-boosted model; and Kishore Kumar Varukolu will handle evaluation, calibration, scheduling simulation, and CooperBench testing. All members will contribute to error analysis and the final report, with a designated lead and reviewer for each section. We will collaborate through a shared GitHub repository, use pull requests for code reviews, track tasks and weekly milestones through GitHub issues, and communicate through weekly meetings and a group chat. Each member will report progress and goals during meetings, and will raise blocked tasks within one day to keep the project on schedule.
