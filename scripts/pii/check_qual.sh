#!/bin/bash

set -e

python scripts/pii_rule_comparison.py \
  --docs-folder /home/ubuntu/s2pdf_dedupe_minhash_v1_with_no_pii/documents \
  --ref-rule "ft_lang_id_en_doc_v2__ft_lang_id_en_doc_v2__en:avg>0.5 and \
              fineweb_edu_fasttext_gt2__fineweb_edu_fasttext_gt2__score:avg>0.001 and \
              avg_fraction_numbers_in_line_v1__avg_fraction_numbers_in_line_v1__avg_fraction_numbers_in_line_ratio:avg<0.2 and \
              pipe_delimited_lines_v1__pipe_delimited_lines_v1__pipe_delimited_lines_ratio:avg<0.3 \
             " \
  --hyp-rule "ft_lang_id_en_doc_v2__ft_lang_id_en_doc_v2__en:avg>0.5 and \
              fineweb_edu_fasttext_gt2__fineweb_edu_fasttext_gt2__score:avg>0.001 and \
              avg_fraction_numbers_in_line_v1__avg_fraction_numbers_in_line_v1__avg_fraction_numbers_in_line_ratio:avg<0.2 and \
              pipe_delimited_lines_v1__pipe_delimited_lines_v1__pipe_delimited_lines_ratio:avg<0.4 \
             " \
  --output-dir results/pii_detection \


# Run1, langid, pipes and numbers
# Prompt, boilerplate, reference, prose, table classification -> train fasttext
# 50k docs to train fast text

tinyhost results/pii_detection/*