"""Standalone presentation figure with complete denominators and unmet gates."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def plot(a):
    report = json.loads(a.metrics.read_text(encoding='utf-8'))
    if report['n_unique_questions'] != 498:
        raise ValueError('Expected complete498 cohort')
    names = {
        'faithfulness': 'Faithfulness', 'factual_precision': 'Factual precision',
        'factual_recall': 'Factual recall', 'context_recall': 'Context recall',
        'context_precision_ap': 'Context precision (AP)', 'answer_relevancy_rubric': 'Answer relevance',
        'actual_citation_link_precision': 'Citation precision', 'actual_citation_claim_recall': 'Citation recall',
    }
    fig, axes = plt.subplots(2, 1, figsize=(11.8, 10), gridspec_kw={'height_ratios': [3.2, 1.2]})
    fig.patch.set_facecolor('#f7f9fc')
    fig.suptitle('Gemini / RAG: 498-question development evaluation', fontsize=19, x=.075, ha='left', y=.97)
    fig.text(.075, .928, f"Frozen application v1.16 | {report['n_valid_judgments']}/498 valid AI audits | all targets not yet met",
             fontsize=11, color='#53627a')
    ax = axes[0]
    keys = list(names)
    y = list(range(len(keys)))
    means = [report['metrics'][k]['macro']*100 for k in keys]
    lower = [report['metrics'][k]['full_cohort_conservative_lower']*100 for k in keys]
    ax.barh(y, means, height=.64, color='#c7dcf2', label='Mean of applicable, measured answers')
    ax.barh(y, lower, height=.34, color='#2064a8', label='Conservative lower bound across all498')
    ax.set_yticks(y, [names[k] for k in keys], fontsize=11)
    ax.invert_yaxis()
    for i, key in enumerate(keys):
        n = report['metrics'][key]['n_measured']
        ax.text(101, i, f'{lower[i]:.2f}% / {means[i]:.2f}%   (n={n}/498)', va='center', fontsize=10, color='#23384f')
    ax.legend(loc='lower left', bbox_to_anchor=(0, -0.18), frameon=False, fontsize=10)
    ax.set_title('Answer and evidence quality', loc='left', fontsize=13, fontweight='bold', pad=12)
    bottom = axes[1]
    strict = report['metrics']['strict_numeric_accuracy']
    complete = report['metrics']['complete_answer_success']
    vals = [strict['strict_lower_bound']*100, complete['strict_lower_bound']*100]
    bottom.barh([0, 1], vals, color='#be4b4b', height=.45)
    bottom.set_yticks([0, 1], ['Strict numeric relations', 'Complete-answer success'], fontsize=11)
    bottom.invert_yaxis()
    for i, (value, count) in enumerate(zip(vals, [f"{strict['n_correct']}/102 relations", f"{complete['n_pass']}/498 answers"])):
        bottom.text(value+2, i, f'{value:.2f}%  ({count})', va='center', fontsize=11, color='#7c2e2e')
    bottom.set_title('Remaining acceptance gaps', loc='left', fontsize=13, fontweight='bold', pad=12)
    for axis in axes:
        axis.set_facecolor('#f7f9fc')
        axis.axvline(80, color='#b37620', linestyle='--', linewidth=1.4)
        axis.set_xlim(0, 142 if axis is ax else 105)
        axis.set_xticks([0, 20, 40, 60, 80, 100], ['0', '20', '40', '60', '80', '100%'])
        axis.grid(axis='x', alpha=.16)
        axis.set_axisbelow(True)
        for spine in axis.spines.values(): spine.set_visible(False)
        axis.tick_params(axis='both', length=0)
    fig.text(.075, .047, 'Dashed line: 80% target. Lower bound gives missing / N/A scores zero, with denominator498.', fontsize=10, color='#53627a')
    fig.text(.075, .025, 'Development data, AI provisional judgments; no independent human certification. Typhoon prose + Gemini tables.', fontsize=9, color='#53627a')
    fig.subplots_adjust(left=.255, right=.965, top=.875, bottom=.115, hspace=.58)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(a.output, dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--metrics', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    plot(p.parse_args())
