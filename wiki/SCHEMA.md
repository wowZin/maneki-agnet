# Wiki Schema — Maneki 股票分析知识库

## Domain

A股涨停预测系统。覆盖扫描策略、五维度评分体系、权重优化、复盘机制。

## Conventions

- File names: lowercase-hyphens, no spaces
- Every wiki page starts with YAML frontmatter
- Use `[[wikilinks]]` to cross-reference (minimum 2 outbound links per page)
- New pages must be added to `index.md`
- Every action appended to `log.md`

## Frontmatter

```yaml
---
title: Page Title
created: YYYY-MM-DD
updated: YYYY-MM-DD
type: entity | concept | comparison | query | summary
tags: [dimension, methodology, data-source, weight, scan, review]
sources: [raw/articles/source.md]
---
```

## Tag Taxonomy

- **dimension**: fundamental, technical, fundflow, sentiment, shortterm
- **methodology**: scoring, ranking, weighting, threshold
- **data-source**: eastmoney, tushare, proxy
- **weight**: optimization, ab-comparison
- **scan**: intraday, closing-review
- **pipeline**: push, feishu, review
- **metric**: auc, hit-rate, coverage, rank

## Page Thresholds

- **Create a page** when a concept appears in 2+ sources or is central to one
- **Don't create** for passing mentions
- **Split** pages over 200 lines

## Entity Pages

One page per notable entity. Include: overview, key facts, relationships.

## Concept Pages

One per concept. Include: definition, methodology, related concepts.
