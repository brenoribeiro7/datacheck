# DataCheck Product Brief

## Problem

Data analysts and data engineers frequently receive datasets from spreadsheets, exports, legacy systems, integrations, vendors, ETL pipelines, and other external sources. Quality checking often depends on manual inspection or one-off scripts, making results difficult to repeat, explain, and retain.

DataCheck addresses the detection of:

- missing required values;
- duplicate values;
- incompatible types;
- out-of-range values;
- invalid formats;
- column inconsistencies.

## Primary user

The primary user is a Data Analyst or Data Engineer who needs a repeatable, explainable assessment before trusting or forwarding a dataset.

## Value proposition

A user uploads a dataset, configures quality rules, and receives an explainable quality analysis with rule-level results, violations, a quality score, and persisted history.

## Core flows

- Identity: registration -> authentication -> access to owned resources.
- Core: CSV upload -> rules -> analysis -> results -> quality score.
- Investigation: dataset -> analysis -> violated rule -> problematic rows.
- History: dataset -> previous analyses -> persisted results.

## First-release requirements

- A web interface is mandatory.
- CSV is the supported ingestion format.
- The maximum ingestion size is 5 GiB, inclusive.
- Processing is asynchronous.
- Validation results are explainable at rule level.
- Analysis history is retained without retaining the original CSV indefinitely.

## Validation rules

- `required`
- `unique`
- `type`
- `min_value`
- `max_value`
- `min_length`
- `max_length`
- `regex`

## Explicit non-goals for the first release

- XLSX, JSON, or Parquet ingestion;
- microservices;
- Kubernetes;
- Kafka or RabbitMQ;
- event sourcing or CQRS;
- generative AI/ML;
- organizations or collaboration;
- billing;
- webhooks;
- S3 or Azure Blob Storage in the initial architecture;
- multiple databases.

External market validation, user interviews, and quantitative product-success targets have not yet been established. Those measurements are future validation work and are not assumed by this baseline.
